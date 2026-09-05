import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime

from src.models import (
    Receivable,
    ReceivableStatusEnum,
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
    RootCause,
    RootCauseEnum,
    ExecutionStatusEnum,
)
from src.db import (
    insert_receivable,
    get_receivable,
    update_receivable_status,
    insert_risk_event,
    insert_root_cause,
    get_risk_event,
)
from src.integrations.config import is_b2b_enabled
from src.outcome_tracker import handle_outcome
from src.audit import log_audit


def evaluate_receivable_root_cause(receivable: Receivable, now: Optional[datetime] = None) -> RootCauseEnum:
    """
    Evaluates the root cause for a B2B receivable based on promise-to-pay date, overdue days, and customer tier.
    """
    ref_time = now or datetime.utcnow()

    # 1. Missed Promise-to-Pay check
    if receivable.promise_to_pay_date and ref_time > receivable.promise_to_pay_date:
        return RootCauseEnum.PROMISE_TO_PAY_MISSED

    # 2. Chronic Non-Payer check (>90 days overdue or explicit tier)
    if receivable.customer_tier == "CHRONIC_NON_PAYER" or receivable.days_overdue > 90:
        return RootCauseEnum.CHRONIC_NON_PAYER

    # 3. Standard Receivable Overdue
    return RootCauseEnum.RECEIVABLE_OVERDUE


def process_b2b_receivable(
    conn: sqlite3.Connection,
    receivable_data: Dict[str, Any],
    simulated_action_outcomes: Optional[Dict[int, ExecutionStatusEnum]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Ingests and processes a B2B receivable through the 8-layer autonomous recovery pipeline.
    Gated strictly by B2B_ENABLED feature flag.
    """
    if not is_b2b_enabled():
        raise PermissionError("B2B Receivables Recovery is disabled (B2B_ENABLED=false)")

    ref_time = now or datetime.utcnow()

    # Parse and validate Receivable model
    due_date = datetime.fromisoformat(receivable_data["due_date"]) if isinstance(receivable_data["due_date"], str) else receivable_data["due_date"]
    p2p_date = None
    if receivable_data.get("promise_to_pay_date"):
        p2p_date = datetime.fromisoformat(receivable_data["promise_to_pay_date"]) if isinstance(receivable_data["promise_to_pay_date"], str) else receivable_data["promise_to_pay_date"]

    days_overdue = receivable_data.get("days_overdue")
    if days_overdue is None:
        days_overdue = max(0, (ref_time - due_date).days)

    receivable = Receivable(
        receivable_id=receivable_data["receivable_id"],
        customer_id=receivable_data["customer_id"],
        invoice_id=receivable_data["invoice_id"],
        amount_due=float(receivable_data["amount_due"]),
        due_date=due_date,
        days_overdue=days_overdue,
        status=ReceivableStatusEnum(receivable_data.get("status", ReceivableStatusEnum.OPEN.value)),
        customer_tier=receivable_data.get("customer_tier", "STANDARD"),
        promise_to_pay_date=p2p_date,
        created_at=ref_time,
    )

    insert_receivable(conn, receivable)

    root_cause_enum = evaluate_receivable_root_cause(receivable, now=ref_time)
    risk_id = f"risk_b2b_{receivable.receivable_id}"

    # Determine priority
    priority = Priority.HIGH if receivable.amount_due >= 10000.0 or receivable.customer_tier == "ENTERPRISE" else Priority.MEDIUM

    risk_event = RiskEvent(
        risk_id=risk_id,
        event_id=f"evt_inv_{receivable.invoice_id}",
        risk_type=RiskType.RECEIVABLE_OVERDUE,
        amount=receivable.amount_due,
        priority=priority,
        status=EventStatus.IN_PROGRESS,
        created_at=ref_time,
    )
    insert_risk_event(conn, risk_event)

    root_cause = RootCause(
        risk_id=risk_id,
        root_cause=root_cause_enum,
        confidence=1.0,
        source="b2b_rule_engine",
        created_at=ref_time,
    )
    insert_root_cause(conn, root_cause)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="b2b_receivables_engine",
        input_data={"receivable_id": receivable.receivable_id, "invoice_id": receivable.invoice_id},
        output_data={"root_cause": root_cause_enum.value, "amount_due": receivable.amount_due},
        decision="b2b_risk_event_initialized",
    )

    # If chronic non-payer -> escalate immediately
    if root_cause_enum == RootCauseEnum.CHRONIC_NON_PAYER:
        from src.db import insert_escalation
        from src.models import Escalation, EscalationStatusEnum
        esc = Escalation(
            risk_id=risk_id,
            reason="b2b_chronic_non_payer_immediate_escalation",
            escalated_at=ref_time,
            status=EscalationStatusEnum.OPEN,
        )
        insert_escalation(conn, esc)
        update_receivable_status(conn, receivable.receivable_id, ReceivableStatusEnum.ESCALATED)
        with conn:
            conn.execute("UPDATE risk_events SET status = ? WHERE risk_id = ?;", (EventStatus.ESCALATED.value, risk_id))
        return {
            "receivable_id": receivable.receivable_id,
            "risk_id": risk_id,
            "status": "ESCALATED",
            "root_cause": root_cause_enum.value,
            "amount_recovered": 0.0,
            "message": "Chronic non-payer escalated immediately to human ops.",
        }

    # Process recovery workflow through start_recovery_workflow
    from src.outcome_tracker import start_recovery_workflow
    wf_result = start_recovery_workflow(
        conn=conn,
        risk_id=risk_id,
        simulated_action_outcomes=simulated_action_outcomes,
        customer_id=receivable.customer_id,
    )

    final_status_str = wf_result.final_status.value
    amount_rec = wf_result.amount_recovered

    if wf_result.final_status == EventStatus.IN_PROGRESS:
        from src.reconciliation import reconcile_payment_status
        recon_res = reconcile_payment_status(
            conn=conn,
            risk_id=risk_id,
            forced_status="RECOVERED",
            verification_source="b2b_simulator",
            source_event="simulated_b2b_payment_confirmation",
        )
        update_receivable_status(conn, receivable.receivable_id, ReceivableStatusEnum.RECOVERED)
        final_status_str = "RECOVERED"
        amount_rec = recon_res.get("amount_recovered", receivable.amount_due)
    elif wf_result.final_status == EventStatus.ESCALATED:
        update_receivable_status(conn, receivable.receivable_id, ReceivableStatusEnum.ESCALATED)

    return {
        "receivable_id": receivable.receivable_id,
        "risk_id": risk_id,
        "status": final_status_str,
        "root_cause": root_cause_enum.value,
        "amount_recovered": amount_rec,
        "workflow_result": wf_result,
    }
