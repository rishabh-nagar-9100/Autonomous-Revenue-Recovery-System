import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from src.models import (
    EventStatus,
    ExecutionStatusEnum,
    OutcomeResultEnum,
    Outcome,
    Escalation,
    EscalationStatusEnum,
)
from src.db import insert_outcome, insert_escalation
from src.audit import log_audit
from src.integrations.razorpay_client import RazorpayClientAdapter
from src.integrations.config import MAX_RECONCILIATION_ATTEMPTS, MAX_RECONCILIATION_HOURS


def reconcile_payment_status(
    conn: sqlite3.Connection,
    risk_id: str,
    forced_status: Optional[str] = None,
    amount: Optional[float] = None,
    attempt_count: int = 1,
    elapsed_hours: float = 0.0,
    auto_resume: bool = False,
    client_adapter: Optional[RazorpayClientAdapter] = None,
    source_event: Optional[str] = None,
    razorpay_payment_id: Optional[str] = None,
    webhook_event_id: Optional[str] = None,
    verification_source: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reconciles payment status for a risk event when webhooks arrive or API status polling is triggered.
    Enforces Monotonic Payment-State Invariant: RECOVERED is terminal and can never be reverted.
    Enforces Financial State Semantics: payment.authorized is pending capture, NOT RECOVERED.
    Enforces Reconciliation Timeout Policy: max 3 attempts OR 24 hours elapsed -> ESCALATED.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT status, amount, created_at FROM risk_events WHERE risk_id = ?;", (risk_id,))
    row = cursor.fetchone()

    if not row:
        return {"status": "not_found", "risk_id": risk_id}

    current_status = row["status"] if hasattr(row, "keys") and "status" in row.keys() else row[0]
    event_amount = (row["amount"] if hasattr(row, "keys") and "amount" in row.keys() else row[1]) if amount is None else amount

    # Monotonic Invariant Check: RECOVERED is terminal
    if current_status == EventStatus.RECOVERED.value:
        audit_mono = {
            "previous_status": current_status,
            "current_status": current_status,
            "attempted_status": forced_status,
            "source_event": source_event or "late_event",
            "verification_source": verification_source or ("razorpay_webhook" if webhook_event_id else "reconciliation_engine"),
        }
        if razorpay_payment_id:
            audit_mono["razorpay_payment_id"] = razorpay_payment_id
        if webhook_event_id:
            audit_mono["webhook_event_id"] = webhook_event_id

        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data=audit_mono,
            output_data={
                "result": "terminal_state_already_reached",
                "note": f"subsequent {source_event or 'event'}; terminal state already reached",
                "current_status": "RECOVERED",
                "terminal_state_preserved": True,
            },
            decision="monotonic_state_preserved",
        )
        return {
            "status": "already_recovered",
            "risk_id": risk_id,
            "message": f"subsequent {source_event or 'event'}; terminal state already reached",
        }

    # If late/older webhook attempts to mark FAILED on a terminal or recovered state -> ignore
    if current_status == EventStatus.RECOVERED.value and forced_status == "FAILED":
        return {
            "status": "ignored_late_failure",
            "risk_id": risk_id,
            "message": "Late failure event ignored on RECOVERED transaction.",
        }

    reconciled_status = forced_status or "RECOVERED"
    now = datetime.utcnow()

    # Case 1: Confirmed SUCCESS / CAPTURED -> transition to RECOVERED
    if reconciled_status in {"RECOVERED", "SUCCESS", "CAPTURED"}:
        with conn:
            conn.execute(
                "UPDATE risk_events SET status = ? WHERE risk_id = ?;",
                (EventStatus.RECOVERED.value, risk_id),
            )

        cursor.execute("SELECT MAX(action_index) as max_idx FROM executions WHERE risk_id = ?;", (risk_id,))
        idx_row = cursor.fetchone()
        action_idx = 0
        if idx_row:
            max_val = idx_row["max_idx"] if hasattr(idx_row, "keys") and "max_idx" in idx_row.keys() else idx_row[0]
            action_idx = max_val if max_val is not None else 0

        # Record verified financial recovery outcome
        with conn:
            conn.execute(
                "UPDATE outcomes SET amount_recovered = ? WHERE risk_id = ? AND action_index = ?;",
                (event_amount, risk_id, action_idx),
            )
        cursor.execute("SELECT 1 FROM outcomes WHERE risk_id = ? AND action_index = ?;", (risk_id, action_idx))
        if not cursor.fetchone():
            outcome = Outcome(
                risk_id=risk_id,
                action_index=action_idx,
                result=OutcomeResultEnum.SUCCESS,
                amount_recovered=event_amount,
                resolved_at=now,
            )
            insert_outcome(conn, outcome)

        resolved_source_event = source_event or (
            "payment.captured" if reconciled_status in {"CAPTURED", "payment.captured"}
            else "order.paid" if reconciled_status in {"order.paid"}
            else "verified_payment"
        )
        resolved_verification_source = verification_source or ("razorpay_webhook" if webhook_event_id else "reconciliation_engine")

        audit_input = {
            "previous_status": current_status,
            "reconciled_status": EventStatus.RECOVERED.value,
            "amount_recovered": event_amount,
            "source_event": resolved_source_event,
            "verification_source": resolved_verification_source,
        }
        if razorpay_payment_id:
            audit_input["razorpay_payment_id"] = razorpay_payment_id
        if webhook_event_id:
            audit_input["webhook_event_id"] = webhook_event_id

        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data=audit_input,
            output_data={
                "risk_id": risk_id,
                "amount_recovered": event_amount,
                "new_status": EventStatus.RECOVERED.value,
                "verified_financial_state": True,
            },
            decision="payment_status_reconciled_recovered",
        )

        return {
            "status": "reconciled",
            "risk_id": risk_id,
            "new_status": EventStatus.RECOVERED.value,
            "amount_recovered": event_amount,
        }

    # Case 2: AUTHORIZED -> Authorized pending capture, NOT RECOVERED
    if reconciled_status in {"AUTHORIZED", "payment.authorized"}:
        resolved_source_event = source_event or "payment.authorized"
        resolved_verification_source = verification_source or ("razorpay_webhook" if webhook_event_id else "reconciliation_engine")

        audit_auth = {
            "previous_status": current_status,
            "reconciled_status": "AUTHORIZED",
            "source_event": resolved_source_event,
            "verification_source": resolved_verification_source,
        }
        if razorpay_payment_id:
            audit_auth["razorpay_payment_id"] = razorpay_payment_id
        if webhook_event_id:
            audit_auth["webhook_event_id"] = webhook_event_id

        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data=audit_auth,
            output_data={
                "risk_id": risk_id,
                "status": "authorized_pending_capture",
                "financial_state": "PENDING_CAPTURE",
                "is_recovered": False,
            },
            decision="payment_authorized_pending_capture",
        )
        return {
            "status": "authorized_pending_capture",
            "risk_id": risk_id,
            "current_status": current_status,
            "message": "Payment authorized but not captured yet. Risk event remains NOT RECOVERED.",
        }

    # Case 3: Confirmed FAILED -> transition to IN_PROGRESS and optionally auto-resume workflow
    if reconciled_status == "FAILED":
        with conn:
            conn.execute(
                "UPDATE risk_events SET status = ? WHERE risk_id = ?;",
                (EventStatus.IN_PROGRESS.value, risk_id),
            )

        resolved_source_event = source_event or "payment.failed"
        resolved_verification_source = verification_source or ("razorpay_webhook" if webhook_event_id else "reconciliation_engine")

        audit_failed = {
            "previous_status": current_status,
            "reconciled_status": "FAILED",
            "source_event": resolved_source_event,
            "verification_source": resolved_verification_source,
        }
        if razorpay_payment_id:
            audit_failed["razorpay_payment_id"] = razorpay_payment_id
        if webhook_event_id:
            audit_failed["webhook_event_id"] = webhook_event_id

        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data=audit_failed,
            output_data={"risk_id": risk_id, "new_status": EventStatus.IN_PROGRESS.value},
            decision="payment_status_reconciled_failed",
        )

        res_workflow = None
        if auto_resume:
            cursor.execute("SELECT MAX(action_index) as max_idx FROM executions WHERE risk_id = ?;", (risk_id,))
            idx_row = cursor.fetchone()
            curr_idx = 0
            if idx_row:
                m = idx_row["max_idx"] if hasattr(idx_row, "keys") and "max_idx" in idx_row.keys() else idx_row[0]
                curr_idx = m if m is not None else 0

            from src.outcome_tracker import handle_outcome
            res_workflow = handle_outcome(
                conn=conn,
                risk_id=risk_id,
                action_index=curr_idx,
                execution_status=ExecutionStatusEnum.FAILED,
            )

        return {
            "status": "reconciled_failed",
            "risk_id": risk_id,
            "new_status": EventStatus.IN_PROGRESS.value,
            "workflow_resumed": auto_resume,
            "workflow_result": res_workflow,
        }

    # Case 4: UNRESOLVED / UNKNOWN -> Check 3 attempts OR 24 hours timeout policy
    if attempt_count >= MAX_RECONCILIATION_ATTEMPTS or elapsed_hours >= MAX_RECONCILIATION_HOURS:
        reason_msg = f"reconciliation_timeout_exhausted: attempts={attempt_count}/{MAX_RECONCILIATION_ATTEMPTS}, elapsed_hours={elapsed_hours}/{MAX_RECONCILIATION_HOURS}"
        with conn:
            conn.execute(
                "UPDATE risk_events SET status = ? WHERE risk_id = ?;",
                (EventStatus.ESCALATED.value, risk_id),
            )

        escalation = Escalation(
            risk_id=risk_id,
            reason=reason_msg,
            escalated_at=now,
            status=EscalationStatusEnum.OPEN,
        )
        insert_escalation(conn, escalation)

        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data={"attempt_count": attempt_count, "elapsed_hours": elapsed_hours},
            output_data=escalation,
            decision="reconciliation_timeout_escalated",
        )

        return {
            "status": "escalated_timeout",
            "risk_id": risk_id,
            "new_status": EventStatus.ESCALATED.value,
            "reason": reason_msg,
        }

    return {
        "status": "pending_reconciliation",
        "risk_id": risk_id,
        "current_status": current_status,
        "attempts": attempt_count,
        "elapsed_hours": elapsed_hours,
    }


def poll_live_razorpay_payments(conn: sqlite3.Connection) -> int:
    """
    Polls active `IN_PROGRESS` live transactions in `live_razorpay.db` against Razorpay's API.
    If Razorpay reports payment status as 'paid' or 'captured', automatically invokes
    `reconcile_payment_status` to transition status to RECOVERED and log full audit trail.
    Returns count of newly reconciled transactions.
    """
    from src.integrations.config import get_execution_mode, ExecutionMode
    if get_execution_mode() != ExecutionMode.SANDBOX:
        return 0

    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.risk_id, r.amount, e.output_json 
        FROM risk_events r
        JOIN audit_log e ON r.risk_id = e.risk_id
        WHERE r.risk_id LIKE 'risk_live_%'
          AND r.status IN ('IN_PROGRESS', 'PENDING_RECONCILIATION', 'DETECTED')
          AND e.layer = 'action_executor'
          AND e.decision = 'action_executed';
    """)
    rows = cursor.fetchall()
    if not rows:
        return 0

    from src.integrations.razorpay_client import RazorpayClientAdapter
    adapter = RazorpayClientAdapter()

    reconciled_count = 0
    checked_links = set()

    for row in rows:
        risk_id = row[0] if not hasattr(row, "keys") else row["risk_id"]
        event_amount = float(row[1] if not hasattr(row, "keys") else row["amount"])
        output_json_str = row[2] if not hasattr(row, "keys") else row["output_json"]

        try:
            import json
            out_data = json.loads(output_json_str)
            details = out_data.get("details", {})
            payment_link_id = details.get("payment_link_id")
            if not payment_link_id or payment_link_id in checked_links or not payment_link_id.startswith("plink_"):
                continue

            checked_links.add(payment_link_id)

            plink = adapter.fetch_payment_link(payment_link_id)
            if not plink:
                continue

            plink_status = plink.get("status")
            if plink_status == "paid":
                payments = plink.get("payments", [])
                payment_id = None
                if isinstance(payments, list) and len(payments) > 0:
                    first_pay = payments[0]
                    if isinstance(first_pay, dict):
                        payment_id = first_pay.get("payment_id") or first_pay.get("id")

                reconcile_payment_status(
                    conn=conn,
                    risk_id=risk_id,
                    forced_status="RECOVERED",
                    amount=event_amount,
                    source_event="payment_link.paid",
                    razorpay_payment_id=payment_id,
                    verification_source="auto_poller_daemon",
                )
                reconciled_count += 1
        except Exception:
            pass

    return reconciled_count

