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

    current_status = row["status"]
    event_amount = row["amount"] if amount is None else amount

    # Monotonic Invariant Check: RECOVERED is terminal
    if current_status == EventStatus.RECOVERED.value:
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data={"current_status": current_status, "attempted_status": forced_status},
            output_data={"result": "ignored_terminal_state"},
            decision="monotonic_state_preserved",
        )
        return {
            "status": "already_recovered",
            "risk_id": risk_id,
            "message": "Transaction is already in terminal RECOVERED state. No change made.",
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
        action_idx = idx_row["max_idx"] if idx_row and idx_row["max_idx"] is not None else 0

        # Check if outcome already exists for this action_index to ensure idempotency
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

        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data={"previous_status": current_status, "reconciled_status": "RECOVERED"},
            output_data={"risk_id": risk_id, "amount_recovered": event_amount},
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
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data={"previous_status": current_status, "reconciled_status": "AUTHORIZED"},
            output_data={"risk_id": risk_id, "status": "authorized_pending_capture"},
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

        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="reconciliation_engine",
            input_data={"previous_status": current_status, "reconciled_status": "FAILED"},
            output_data={"risk_id": risk_id, "new_status": EventStatus.IN_PROGRESS.value},
            decision="payment_status_reconciled_failed",
        )

        res_workflow = None
        if auto_resume:
            cursor.execute("SELECT MAX(action_index) as max_idx FROM executions WHERE risk_id = ?;", (risk_id,))
            idx_row = cursor.fetchone()
            curr_idx = idx_row["max_idx"] if idx_row and idx_row["max_idx"] is not None else 0

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
