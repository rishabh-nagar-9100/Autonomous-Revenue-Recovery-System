from typing import Optional, Dict, Any
from datetime import datetime
import sqlite3
from pydantic import BaseModel, Field
from src.models import (
    EventStatus,
    ActionType,
    ExecutionStatusEnum,
    OutcomeResultEnum,
    Outcome,
    Escalation,
    EscalationStatusEnum,
    GuardrailResultEnum,
    RootCauseEnum,
)
from src.db import (
    get_risk_event,
    get_root_cause,
    update_risk_event_status,
    insert_outcome,
    insert_escalation,
)
from src.decision_engine import next_action, record_intervention
from src.guardrails import GuardrailContext, evaluate_and_record_guardrails
from src.executor import execute_action
from src.audit import log_audit


class WorkflowResult(BaseModel):
    risk_id: str
    final_status: EventStatus
    amount_recovered: float = 0.0
    reason: Optional[str] = None
    actions_executed_count: int = 0
    resolved_at: datetime = Field(default_factory=datetime.utcnow)


def record_escalation(
    conn: sqlite3.Connection,
    risk_id: str,
    reason: str,
) -> Escalation:
    """Creates, persists an Escalation record, and logs an audit trail entry."""
    escalation = Escalation(
        risk_id=risk_id,
        reason=reason,
        escalated_at=datetime.utcnow(),
        status=EscalationStatusEnum.OPEN,
    )
    insert_escalation(conn, escalation)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="escalation_handler",
        input_data={"reason": reason},
        output_data=escalation,
        decision="escalated",
    )

    return escalation


def handle_outcome(
    conn: sqlite3.Connection,
    risk_id: str,
    action_index: int,
    execution_status: ExecutionStatusEnum,
    context: Optional[GuardrailContext] = None,
    simulated_action_outcomes: Optional[Dict[int, ExecutionStatusEnum]] = None,
    customer_id: str = "customer_unknown",
) -> WorkflowResult:
    """
    Core Outcome Tracker driving the closed-loop recovery workflow:
    1. SUCCESS:
       - Log outcome (result=SUCCESS, amount_recovered=risk_event.amount).
       - Mark risk event RECOVERED and log revenue_recovered audit transition.
       - Hard-stop workflow (no further actions).
    2. FAILED:
       - Log outcome (result=FAILED, amount_recovered=0.0).
       - Query deterministic Decision Engine for next_action(root_cause, action_index + 1).
       - If no action exists -> Escalate with reason 'playbook_exhausted'.
       - If action exists:
         - Re-evaluate Guardrails for the next action.
         - If guardrail BLOCKS -> Hard-stop immediately and Escalate (do NOT execute action).
         - If guardrail PASSES -> Execute action and loop back to handle_outcome.
    """
    risk_event = get_risk_event(conn, risk_id)
    if not risk_event:
        raise ValueError(f"Risk event with risk_id '{risk_id}' not found.")

    root_cause = get_root_cause(conn, risk_id)
    if not root_cause:
        raise ValueError(f"Root cause for risk_id '{risk_id}' not found.")

    sim_outcomes = simulated_action_outcomes or {}
    now = datetime.utcnow()

    # 1. Handle Action Execution SUCCESS (Action dispatched, awaiting payment reconciliation)
    if execution_status == ExecutionStatusEnum.SUCCESS:
        outcome = Outcome(
            risk_id=risk_id,
            action_index=action_index,
            result=OutcomeResultEnum.SUCCESS,
            amount_recovered=0.0,
            resolved_at=now,
        )
        insert_outcome(conn, outcome)
        update_risk_event_status(conn, risk_id, EventStatus.IN_PROGRESS)

        # Audit logs for action execution outcome
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="outcome_tracker",
            input_data={"action_index": action_index, "execution_status": execution_status.value},
            output_data=outcome,
            decision="outcome_recorded",
        )
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="outcome_tracker",
            input_data={"action_index": action_index, "execution_status": execution_status.value},
            output_data={
                "status": "IN_PROGRESS",
                "amount_recovered": 0.0,
                "financial_recovery_verified": False,
                "message": "Action execution succeeded; awaiting verified financial recovery payment.",
            },
            decision="action_execution_succeeded",
        )

        return WorkflowResult(
            risk_id=risk_id,
            final_status=EventStatus.IN_PROGRESS,
            amount_recovered=0.0,
            reason=None,
            actions_executed_count=action_index + 1,
            resolved_at=now,
        )


    # 1b. Handle PENDING_RECONCILIATION Safety Halt
    if execution_status == ExecutionStatusEnum.PENDING_RECONCILIATION:
        update_risk_event_status(conn, risk_id, EventStatus.PENDING_RECONCILIATION)
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="outcome_tracker",
            input_data={"action_index": action_index, "execution_status": execution_status.value},
            output_data={"status": "PENDING_RECONCILIATION", "message": "Safety halt: awaiting status reconciliation before next action."},
            decision="pending_reconciliation_safety_halt",
        )
        return WorkflowResult(
            risk_id=risk_id,
            final_status=EventStatus.PENDING_RECONCILIATION,
            amount_recovered=0.0,
            reason="pending_reconciliation_safety_halt",
            actions_executed_count=action_index + 1,
            resolved_at=now,
        )

    # 2. Handle FAILED
    outcome = Outcome(
        risk_id=risk_id,
        action_index=action_index,
        result=OutcomeResultEnum.FAILED,
        amount_recovered=0.0,
        resolved_at=now,
    )
    insert_outcome(conn, outcome)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="outcome_tracker",
        input_data={"action_index": action_index, "execution_status": execution_status.value},
        output_data=outcome,
        decision="outcome_recorded",
    )

    # Query next action from deterministic PLAYBOOK
    next_idx = action_index + 1
    next_act = next_action(root_cause.root_cause, next_idx)

    # If end of playbook reached -> escalate
    if next_act is None:
        record_escalation(conn, risk_id, reason="playbook_exhausted")
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        return WorkflowResult(
            risk_id=risk_id,
            final_status=EventStatus.ESCALATED,
            amount_recovered=0.0,
            reason="playbook_exhausted",
            actions_executed_count=action_index + 1,
            resolved_at=now,
        )

    # Record intervention for next action
    record_intervention(
        conn=conn,
        risk_id=risk_id,
        action_index=next_idx,
        action_type=next_act,
    )

    # Re-evaluate Guardrail Layer
    guardrail_check = evaluate_and_record_guardrails(
        conn=conn,
        risk_id=risk_id,
        amount=risk_event.amount,
        action_index=next_idx,
        action_type=next_act,
        context=context,
    )

    # Guardrail BLOCK -> Hard stop immediately!
    if guardrail_check.result == GuardrailResultEnum.BLOCK:
        block_reason = f"guardrail_blocked:{guardrail_check.reason}"
        record_escalation(conn, risk_id, reason=block_reason)
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        return WorkflowResult(
            risk_id=risk_id,
            final_status=EventStatus.ESCALATED,
            amount_recovered=0.0,
            reason=block_reason,
            actions_executed_count=action_index + 1,  # Blocked action was NOT executed
            resolved_at=now,
        )

    # Guardrail PASS -> Execute next action and continue the loop
    sim_status = sim_outcomes.get(next_idx, ExecutionStatusEnum.SUCCESS)
    exec_res = execute_action(
        risk_id=risk_id,
        action_index=next_idx,
        action_type=next_act,
        amount=risk_event.amount,
        customer_id=customer_id,
        simulate_status=sim_status,
        conn=conn,
    )

    # Loop back with the outcome of this execution
    return handle_outcome(
        conn=conn,
        risk_id=risk_id,
        action_index=next_idx,
        execution_status=exec_res.status,
        context=context,
        simulated_action_outcomes=sim_outcomes,
        customer_id=customer_id,
    )


def start_recovery_workflow(
    conn: sqlite3.Connection,
    risk_id: str,
    context: Optional[GuardrailContext] = None,
    simulated_action_outcomes: Optional[Dict[int, ExecutionStatusEnum]] = None,
    customer_id: str = "customer_unknown",
) -> WorkflowResult:
    """
    Initiates the recovery loop starting from action index 0.
    """
    risk_event = get_risk_event(conn, risk_id)
    if not risk_event:
        raise ValueError(f"Risk event with risk_id '{risk_id}' not found.")

    root_cause = get_root_cause(conn, risk_id)
    if not root_cause:
        raise ValueError(f"Root cause for risk_id '{risk_id}' not found.")

    update_risk_event_status(conn, risk_id, EventStatus.IN_PROGRESS)

    sim_outcomes = simulated_action_outcomes or {}
    now = datetime.utcnow()

    # Handle UNKNOWN root cause -> attempt Bounded Customer Clarification (Phase 13)
    if root_cause.root_cause == RootCauseEnum.UNKNOWN and not risk_id.startswith("risk_pay_syn_"):
        from src.integrations.config import is_info_gathering_enabled
        from src.info_gathering import can_request_info, request_customer_info

        if is_info_gathering_enabled() and can_request_info(conn, risk_id):
            info_res = request_customer_info(
                conn=conn,
                risk_id=risk_id,
                amount=risk_event.amount,
                customer_id=customer_id,
                context=context,
            )
            if info_res.get("status") == "requested":
                return WorkflowResult(
                    risk_id=risk_id,
                    final_status=EventStatus.WAITING_FOR_CUSTOMER_INFO,
                    amount_recovered=0.0,
                    reason="info_clarification_requested",
                    actions_executed_count=0,
                    resolved_at=now,
                )

    # Step 0 action
    act_0 = next_action(root_cause.root_cause, 0)
    if act_0 is None:
        # Empty playbook (e.g. chronic_non_payer) or unhandled unknown
        record_escalation(conn, risk_id, reason="playbook_exhausted")
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        return WorkflowResult(
            risk_id=risk_id,
            final_status=EventStatus.ESCALATED,
            amount_recovered=0.0,
            reason="playbook_exhausted",
            actions_executed_count=0,
            resolved_at=now,
        )

    from src.llm import draft_action_message_llm
    draft_msg = draft_action_message_llm(
        risk_id=risk_id,
        action_type=act_0,
        amount=risk_event.amount,
        customer_id=customer_id,
        root_cause=root_cause.root_cause,
    )

    # Record intervention 0
    record_intervention(
        conn=conn,
        risk_id=risk_id,
        action_index=0,
        action_type=act_0,
        draft_message=draft_msg,
    )

    # Guardrail check 0
    check_0 = evaluate_and_record_guardrails(
        conn=conn,
        risk_id=risk_id,
        amount=risk_event.amount,
        action_index=0,
        action_type=act_0,
        context=context,
    )

    if check_0.result == GuardrailResultEnum.BLOCK:
        block_reason = f"guardrail_blocked:{check_0.reason}"
        record_escalation(conn, risk_id, reason=block_reason)
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        return WorkflowResult(
            risk_id=risk_id,
            final_status=EventStatus.ESCALATED,
            amount_recovered=0.0,
            reason=block_reason,
            actions_executed_count=0,
            resolved_at=now,
        )

    # Execute action 0
    sim_status_0 = sim_outcomes.get(0, ExecutionStatusEnum.SUCCESS)
    exec_0 = execute_action(
        risk_id=risk_id,
        action_index=0,
        action_type=act_0,
        amount=risk_event.amount,
        customer_id=customer_id,
        simulate_status=sim_status_0,
        conn=conn,
    )

    # Transition to Outcome Tracker loop
    return handle_outcome(
        conn=conn,
        risk_id=risk_id,
        action_index=0,
        execution_status=exec_0.status,
        context=context,
        simulated_action_outcomes=sim_outcomes,
        customer_id=customer_id,
    )
