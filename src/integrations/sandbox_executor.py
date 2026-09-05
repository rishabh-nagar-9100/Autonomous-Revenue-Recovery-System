import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from src.models import (
    ActionType,
    ExecutionStatusEnum,
    ExecutionResult,
)
from src.integrations.config import DEMO_FALLBACK_TO_MOCK
from src.integrations.razorpay_client import RazorpayClientAdapter


def execute_sandbox_payment_link(
    risk_id: str,
    amount: float,
    customer_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    client_adapter: Optional[RazorpayClientAdapter] = None,
) -> ExecutionResult:
    """
    Executes a real Razorpay Test/Sandbox Payment Link creation.
    Strict mode separation constraint: On API error, if DEMO_FALLBACK_TO_MOCK is False,
    returns structured FAILED status. Never performs silent mock fallback unless DEMO_FALLBACK_TO_MOCK=True.
    """
    meta = metadata or {}
    now = datetime.utcnow()
    execution_id = f"exec_sandbox_payment_link_{uuid.uuid4().hex[:12]}"

    if risk_id.startswith("risk_pay_syn_"):
        raise ValueError(
            f"Routing Invariant Violation: Synthetic risk event '{risk_id}' cannot be executed with Razorpay Sandbox. "
            "Synthetic events must use deterministic mock execution only."
        )

    adapter = client_adapter or RazorpayClientAdapter()

    try:
        res = adapter.create_payment_link(
            amount=amount,
            customer_id=customer_id,
            description=f"Recovery Payment for Risk {risk_id}",
            reference_id=risk_id,
        )
        return ExecutionResult(
            execution_id=execution_id,
            action_type=ActionType.PAYMENT_LINK,
            status=ExecutionStatusEnum.SUCCESS,
            details={
                "action": "payment_link",
                "payment_link_id": res.get("payment_link_id"),
                "short_url": res.get("short_url"),
                "status": res.get("status"),
                "execution_mode": "sandbox",
                "simulated": False,
            },
            executed_at=now,
        )
    except Exception as exc:
        error_msg = str(exc)

        # Check explicit demo mode opt-in fallback
        if DEMO_FALLBACK_TO_MOCK:
            mock_link_id = f"plink_mock_fallback_{uuid.uuid4().hex[:8]}"
            return ExecutionResult(
                execution_id=execution_id,
                action_type=ActionType.PAYMENT_LINK,
                status=ExecutionStatusEnum.SUCCESS,
                details={
                    "action": "payment_link",
                    "payment_link_id": mock_link_id,
                    "short_url": f"https://rzp.io/i/{mock_link_id}",
                    "execution_mode": "sandbox",
                    "fallback_applied": True,
                    "fallback_reason": f"demo_mode_api_error: {error_msg}",
                    "simulated": True,
                },
                executed_at=now,
            )

        # Strict mode separation — return structured failure, no silent mock execution
        return ExecutionResult(
            execution_id=execution_id,
            action_type=ActionType.PAYMENT_LINK,
            status=ExecutionStatusEnum.FAILED,
            details={
                "action": "payment_link",
                "execution_mode": "sandbox",
                "error": error_msg,
                "fallback_applied": False,
                "simulated": False,
            },
            executed_at=now,
        )
