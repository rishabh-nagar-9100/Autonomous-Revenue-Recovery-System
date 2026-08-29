import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from src.models import (
    EventStatus,
    RootCauseEnum,
    ActionType,
    ExecutionStatusEnum,
    InfoRequest,
    InfoRequestStatusEnum,
    GuardrailResultEnum,
)
from src.db import (
    get_risk_event,
    update_risk_event_status,
    insert_info_request,
    get_info_request,
    update_info_request,
    update_root_cause,
)
from src.integrations.config import is_info_gathering_enabled, INFO_RECOVERY_WINDOW_DAYS
from src.guardrails import GuardrailContext, evaluate_and_record_guardrails
from src.outcome_tracker import record_escalation, start_recovery_workflow
from src.audit import log_audit


def can_request_info(conn: sqlite3.Connection, risk_id: str) -> bool:
    """
    Checks whether an information clarification request can be initiated.
    Enforces:
    1. INFO_GATHERING_ENABLED feature flag must be true.
    2. Exactly ONE clarification request allowed per risk_id (no second attempt).
    """
    if not is_info_gathering_enabled():
        return False

    existing_req = get_info_request(conn, risk_id)
    if existing_req is not None:
        return False

    return True


def generate_clarification_question(risk_id: str, amount: float, customer_id: str) -> str:
    """Drafts a polite, bounded customer clarification question."""
    return f"Hi, your payment of ₹{amount:,.2f} could not be completed. Could you please let us know what went wrong (e.g. card expired, insufficient funds, bank technical error) so we can assist you?"


def request_customer_info(
    conn: sqlite3.Connection,
    risk_id: str,
    amount: float,
    customer_id: str,
    context: Optional[GuardrailContext] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Initiates customer clarification request.
    Evaluates communication guardrails (DND, opt-out) before sending.
    """
    ref_time = now or datetime.utcnow()

    if context is None:
        context = GuardrailContext(current_time=ref_time)

    # 1. Feature Flag & Attempt Limit Check
    if not can_request_info(conn, risk_id):
        reason = "info_gathering_disabled" if not is_info_gathering_enabled() else "info_gathering_attempt_limit_exceeded"
        record_escalation(conn, risk_id, reason=reason)
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="info_gathering_engine",
            input_data={"reason": reason},
            output_data={"status": "ESCALATED"},
            decision="info_request_blocked_escalated",
        )
        return {"status": "blocked", "reason": reason, "escalated": True}

    # 2. Evaluate Communication Guardrails (DND, Opt-out)
    guardrail_check = evaluate_and_record_guardrails(
        conn=conn,
        risk_id=risk_id,
        amount=amount,
        action_index=-1,
        action_type=ActionType.REMINDER,
        context=context,
    )

    if guardrail_check.result == GuardrailResultEnum.BLOCK:
        block_reason = f"guardrail_blocked:{guardrail_check.reason}"
        record_escalation(conn, risk_id, reason=block_reason)
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="info_gathering_engine",
            input_data={"guardrail_reason": guardrail_check.reason},
            output_data={"status": "ESCALATED"},
            decision="info_request_guardrail_blocked_escalated",
        )
        return {"status": "guardrail_blocked", "reason": block_reason, "escalated": True}

    # 3. Create InfoRequest and set status WAITING_FOR_CUSTOMER_INFO
    question = generate_clarification_question(risk_id, amount, customer_id)
    info_req = InfoRequest(
        risk_id=risk_id,
        question=question,
        status=InfoRequestStatusEnum.REQUESTED,
        requested_at=ref_time,
    )
    insert_info_request(conn, info_req)

    update_risk_event_status(conn, risk_id, EventStatus.WAITING_FOR_CUSTOMER_INFO)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="info_gathering_engine",
        input_data={"question": question},
        output_data=info_req,
        decision="info_clarification_requested",
    )

    return {
        "status": "requested",
        "question": question,
        "risk_id": risk_id,
        "event_status": EventStatus.WAITING_FOR_CUSTOMER_INFO.value,
    }


def parse_customer_response(response_text: str) -> Optional[RootCauseEnum]:
    """
    Parses customer response and maps strictly into valid fixed RootCauseEnum values.
    Returns None for gibberish, ambiguous, unsupported, or invalid responses.
    Never returns free-form strings.
    """
    if not response_text or not isinstance(response_text, str):
        return None

    text = response_text.lower().strip()

    # Bounded keyword & intent mapping to fixed RootCauseEnum
    if any(k in text for k in ["expire", "expiry", "card expired", "validity"]):
        return RootCauseEnum.EXPIRED_CARD
    if any(k in text for k in ["insufficient", "nsf", "balance", "funds", "low balance", "paise nahi"]):
        return RootCauseEnum.NSF
    if any(k in text for k in ["bank", "timeout", "server", "network", "otp", "technical", "down"]):
        return RootCauseEnum.BANK_TIMEOUT
    if any(k in text for k in ["forgot", "delay", "overdue", "later", "time"]):
        return RootCauseEnum.RECENT_OVERDUE
    if any(k in text for k in ["cart", "abandon", "cancelled"]):
        return RootCauseEnum.CART_ABANDONMENT

    return None


def check_recovery_eligibility(conn: sqlite3.Connection, risk_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Verifies recovery eligibility before resuming workflow:
    - Transaction not already RECOVERED or ESCALATED
    - Elapsed time <= INFO_RECOVERY_WINDOW_DAYS (7 days)
    - Amount valid (>0)
    """
    ref_time = now or datetime.utcnow()
    risk_event = get_risk_event(conn, risk_id)

    if not risk_event:
        return {"eligible": False, "reason": "risk_event_not_found"}

    if risk_event.status == EventStatus.RECOVERED:
        return {"eligible": False, "reason": "already_recovered"}

    if risk_event.status == EventStatus.ESCALATED:
        return {"eligible": False, "reason": "already_escalated"}

    if risk_event.amount <= 0:
        return {"eligible": False, "reason": "invalid_amount"}

    elapsed_days = (ref_time - risk_event.created_at).total_seconds() / 86400.0
    if elapsed_days > INFO_RECOVERY_WINDOW_DAYS:
        return {"eligible": False, "reason": f"recovery_window_expired: {elapsed_days:.1f} days > {INFO_RECOVERY_WINDOW_DAYS} days"}

    return {"eligible": True, "reason": "PASS"}


def process_customer_info_response(
    conn: sqlite3.Connection,
    risk_id: str,
    response_text: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Processes customer clarification response:
    - Verifies current state is WAITING_FOR_CUSTOMER_INFO.
    - Extracts structured root cause.
    - If unusable/gibberish -> escalates.
    - If supported -> performs recovery eligibility check.
    - If eligibility passes -> updates root cause and resumes recovery workflow.
    """
    ref_time = now or datetime.utcnow()
    risk_event = get_risk_event(conn, risk_id)

    if not risk_event:
        return {"status": "not_found", "risk_id": risk_id}

    # If already recovered -> ignore response and do not resume payment recovery
    if risk_event.status == EventStatus.RECOVERED:
        return {
            "status": "ignored",
            "reason": "already_recovered",
            "message": "Transaction is already in terminal RECOVERED state. Response ignored.",
        }

    # Verify transaction is in WAITING_FOR_CUSTOMER_INFO or INFO_REQUESTED state
    if risk_event.status not in {EventStatus.WAITING_FOR_CUSTOMER_INFO, EventStatus.INFO_REQUESTED}:
        return {
            "status": "ignored",
            "reason": "not_waiting_for_info",
            "current_status": risk_event.status.value,
        }

    # 1. Parse customer response
    extracted_cause = parse_customer_response(response_text)

    if extracted_cause is None:
        update_info_request(
            conn=conn,
            risk_id=risk_id,
            response=response_text,
            extracted_root_cause=None,
            status=InfoRequestStatusEnum.FAILED,
            responded_at=ref_time,
            eligibility_check_result="FAILED_UNUSABLE_RESPONSE",
        )
        record_escalation(conn, risk_id, reason="unusable_info_response")
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="info_gathering_engine",
            input_data={"response": response_text},
            output_data={"extracted_root_cause": None},
            decision="info_response_unusable_escalated",
        )
        return {"status": "escalated", "reason": "unusable_info_response"}

    # 2. Check Recovery Eligibility
    eligibility = check_recovery_eligibility(conn, risk_id, now=ref_time)

    if not eligibility["eligible"]:
        update_info_request(
            conn=conn,
            risk_id=risk_id,
            response=response_text,
            extracted_root_cause=extracted_cause.value,
            status=InfoRequestStatusEnum.ELIGIBILITY_FAILED,
            responded_at=ref_time,
            eligibility_check_result=eligibility["reason"],
        )
        reason_msg = f"eligibility_check_failed:{eligibility['reason']}"
        record_escalation(conn, risk_id, reason=reason_msg)
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="info_gathering_engine",
            input_data={"extracted_root_cause": extracted_cause.value},
            output_data={"eligibility": eligibility},
            decision="info_recovery_eligibility_failed_escalated",
        )
        return {"status": "escalated", "reason": eligibility["reason"]}

    # 3. Eligibility Passed -> Update Root Cause, Mark InfoRequest RESOLVED, and Resume Workflow
    update_root_cause(conn, risk_id, extracted_cause, source="customer_info_clarification")
    update_info_request(
        conn=conn,
        risk_id=risk_id,
        response=response_text,
        extracted_root_cause=extracted_cause.value,
        status=InfoRequestStatusEnum.RESOLVED,
        responded_at=ref_time,
        eligibility_check_result="PASS",
    )
    update_risk_event_status(conn, risk_id, EventStatus.IN_PROGRESS)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="info_gathering_engine",
        input_data={"response": response_text},
        output_data={"extracted_root_cause": extracted_cause.value, "eligibility": "PASS"},
        decision="info_response_resolved_resuming_workflow",
    )

    wf_result = start_recovery_workflow(conn, risk_id)

    return {
        "status": "resumed",
        "extracted_root_cause": extracted_cause.value,
        "workflow_result": wf_result,
    }


def handle_info_timeout(conn: sqlite3.Connection, risk_id: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Handles timeout when customer does not respond to clarification request."""
    ref_time = now or datetime.utcnow()

    update_info_request(
        conn=conn,
        risk_id=risk_id,
        status=InfoRequestStatusEnum.TIMED_OUT,
        eligibility_check_result="TIMED_OUT",
    )
    record_escalation(conn, risk_id, reason="info_request_timeout")
    update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="info_gathering_engine",
        input_data={"event": "timeout"},
        output_data={"status": "ESCALATED"},
        decision="info_request_timed_out_escalated",
    )

    return {"status": "escalated", "reason": "info_request_timeout"}
