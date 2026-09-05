import uuid
from typing import Optional, Dict, Any
from datetime import datetime
import sqlite3
from src.models import (
    ActionType,
    ExecutionStatusEnum,
    Execution,
    ExecutionResult,
)
from src.db import insert_execution


def generate_execution_id(action_type: ActionType) -> str:
    """Generates a deterministic unique execution_id format."""
    unique_suffix = uuid.uuid4().hex[:12]
    return f"exec_{action_type.value}_{unique_suffix}"


def execute_smart_retry(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of Razorpay Smart Routing retry."""
    return {
        "action": "smart_retry",
        "gateway_route": metadata.get("preferred_gateway", "hdfc_optimized_route"),
        "routing_latency_ms": 142,
        "simulated": True,
    }


def execute_payment_link(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of Razorpay Payment Links API."""
    link_id = f"plink_{uuid.uuid4().hex[:10]}"
    return {
        "action": "payment_link",
        "payment_link_id": link_id,
        "short_url": f"https://rzp.io/i/{link_id}",
        "expires_in_hours": 72,
        "simulated": True,
    }


def execute_delayed_retry(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of Delayed / Scheduled Retry."""
    return {
        "action": "delayed_retry",
        "scheduled_delay_hours": 4,
        "retry_queue": "delayed_recovery_queue",
        "simulated": True,
    }


def execute_reminder(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of Customer Notification / Reminder."""
    msg_id = f"msg_{uuid.uuid4().hex[:10]}"
    return {
        "action": "reminder",
        "channel": metadata.get("channel", "whatsapp"),
        "message_id": msg_id,
        "simulated": True,
    }


def execute_discount_nudge(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of Cart Recovery Discount Nudge."""
    return {
        "action": "discount_nudge",
        "coupon_code": "RECOVER10",
        "discount_percent": 10.0,
        "simulated": True,
    }


def execute_escalate(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of Human Agent Escalation / CRM Ticketing."""
    ticket_id = f"tkt_{uuid.uuid4().hex[:8]}"
    return {
        "action": "escalate",
        "ticket_id": ticket_id,
        "queue": "high_priority_revenue_recovery",
        "simulated": True,
    }


def execute_escalate_to_crm(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of CRM Escalation for B2B Receivables."""
    case_id = f"crm_{uuid.uuid4().hex[:8]}"
    return {
        "action": "escalate_to_crm",
        "crm_case_id": case_id,
        "queue": "b2b_account_management",
        "simulated": True,
    }


def execute_escalate_to_collections(
    risk_id: str,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Mocked implementation of External Collections Escalation for B2B Receivables."""
    case_id = f"col_{uuid.uuid4().hex[:8]}"
    return {
        "action": "escalate_to_collections",
        "collections_case_id": case_id,
        "agency": "enterprise_collections_partner",
        "simulated": True,
    }


ACTION_HANDLERS = {
    ActionType.SMART_RETRY: execute_smart_retry,
    ActionType.PAYMENT_LINK: execute_payment_link,
    ActionType.DELAYED_RETRY: execute_delayed_retry,
    ActionType.REMINDER: execute_reminder,
    ActionType.DISCOUNT_NUDGE: execute_discount_nudge,
    ActionType.ESCALATE: execute_escalate,
    ActionType.ESCALATE_TO_CRM: execute_escalate_to_crm,
    ActionType.ESCALATE_TO_COLLECTIONS: execute_escalate_to_collections,
}


def execute_action(
    risk_id: str,
    action_index: int,
    action_type: ActionType,
    amount: float,
    customer_id: str,
    simulate_status: ExecutionStatusEnum = ExecutionStatusEnum.SUCCESS,
    metadata: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> ExecutionResult:
    """
    Executes a pre-approved action within controlled boundaries.
    Generates unique execution_id and optionally persists to executions table.
    """
    if not isinstance(action_type, ActionType):
        try:
            action_type = ActionType(action_type)
        except ValueError:
            raise ValueError(f"Invalid or unsupported action_type: {action_type}")

    handler = ACTION_HANDLERS.get(action_type)
    if not handler:
        raise ValueError(f"No execution handler registered for action_type: {action_type}")

    meta = metadata or {}
    now = datetime.utcnow()

    from src.integrations.config import get_execution_mode, ExecutionMode
    mode = get_execution_mode()

    # Routing Invariant:
    # Synthetic: risk_pay_syn_* -> DETERMINISTIC MOCK ONLY (simulated=True, execution_mode="mock", NO Razorpay API)
    # Live: risk_live_* -> RAZORPAY SANDBOX (simulated=False, execution_mode="sandbox", real Razorpay API)
    is_live_risk = risk_id.startswith("risk_live_") or (
        not risk_id.startswith("risk_pay_syn_") and mode == ExecutionMode.SANDBOX and ("sbx" in risk_id or "route_2" in risk_id)
    )

    if mode == ExecutionMode.SANDBOX and action_type == ActionType.PAYMENT_LINK and is_live_risk:
        from src.integrations.sandbox_executor import execute_sandbox_payment_link
        result = execute_sandbox_payment_link(
            risk_id=risk_id,
            amount=amount,
            customer_id=customer_id,
            metadata=meta,
        )
        actual_execution_mode = "sandbox"
    else:
        execution_id = generate_execution_id(action_type)
        # Execute controlled mock handler
        details = handler(
            risk_id=risk_id,
            amount=amount,
            customer_id=customer_id,
            simulate_status=simulate_status,
            metadata=meta,
        )
        # Strictly tag mock executions as mock, never sandbox
        actual_execution_mode = "mock"
        details["execution_mode"] = actual_execution_mode
        details["simulated"] = True

        result = ExecutionResult(
            execution_id=execution_id,
            action_type=action_type,
            status=simulate_status,
            details=details,
            executed_at=now,
        )

    # Persist execution to database if connection provided
    if conn is not None:
        db_execution = Execution(
            risk_id=risk_id,
            action_index=action_index,
            action_type=action_type,
            execution_id=result.execution_id,
            status=result.status,
            executed_at=result.executed_at,
        )
        insert_execution(conn, db_execution)

        from src.audit import log_audit
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="action_executor",
            input_data={
                "action_index": action_index,
                "action_type": action_type.value,
                "amount": amount,
                "customer_id": customer_id,
                "execution_mode": actual_execution_mode,
            },
            output_data=result,
            decision="action_executed",
        )

    return result
