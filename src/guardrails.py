from typing import Optional, Set
from datetime import datetime, time
import sqlite3
from pydantic import BaseModel, Field
from src.models import (
    RiskEvent,
    ActionType,
    GuardrailResultEnum,
    GuardrailCheck,
)
from src.db import insert_guardrail_check


CUSTOMER_FACING_ACTIONS: Set[ActionType] = {
    ActionType.PAYMENT_LINK,
    ActionType.REMINDER,
    ActionType.DISCOUNT_NUDGE,
}

RETRY_ACTIONS: Set[ActionType] = {
    ActionType.SMART_RETRY,
    ActionType.DELAYED_RETRY,
}

# DND window: 9:00 AM to 8:00 PM (09:00 to 20:00)
DND_START_HOUR = 9
DND_END_HOUR = 20

# Max retry attempts allowed
MAX_RETRY_ATTEMPTS = 4

# Cooldown duration between retries in seconds (4 hours)
COOLDOWN_SECONDS = 4 * 3600

# Default amount threshold requiring human approval (in INR)
DEFAULT_HUMAN_APPROVAL_AMOUNT_THRESHOLD = 50000.0


def is_dnd_hours(current_time: datetime) -> bool:
    """Returns True if current_time falls outside 9am-8pm (09:00 to 20:00)."""
    hour = current_time.hour
    return hour < DND_START_HOUR or hour >= DND_END_HOUR


def default_guardrail_time() -> datetime:
    now = datetime.now()
    if now.hour >= 20 or now.hour < 9:
        return now.replace(hour=14, minute=0, second=0, microsecond=0)
    return now


class GuardrailContext(BaseModel):
    attempt_number: int = 1
    is_mandate: bool = False
    mandate_notice_served: bool = True
    last_retry_at: Optional[datetime] = None
    current_time: datetime = Field(default_factory=default_guardrail_time)
    customer_opted_out: bool = False
    human_approval_threshold: float = DEFAULT_HUMAN_APPROVAL_AMOUNT_THRESHOLD


def evaluate_guardrails(
    risk_id: str,
    amount: float,
    action_index: int,
    action_type: ActionType,
    context: Optional[GuardrailContext] = None,
) -> GuardrailCheck:
    """
    Deterministic Guardrail Layer evaluating proposed actions in strict priority order:
    1. retry_cap_exceeded (max 4 attempts total per transaction)
    2. mandate_notice_required (RBI e-mandate pre-debit notice window)
    3. cooldown_active (no more than 1 retry per 4h on same transaction)
    4. dnd_hours (no customer-facing action outside 9am-8pm)
    5. customer_opted_out (skip customer-facing actions if opted out)
    6. amount_requires_human_approval (above threshold, always escalate)
    """
    ctx = context or GuardrailContext()
    checked_at = ctx.current_time

    # 1. retry_cap_exceeded
    if ctx.attempt_number > MAX_RETRY_ATTEMPTS:
        return GuardrailCheck(
            risk_id=risk_id,
            action_index=action_index,
            result=GuardrailResultEnum.BLOCK,
            reason="retry_cap_exceeded",
            checked_at=checked_at,
        )

    # 2. mandate_notice_required
    if ctx.is_mandate and not ctx.mandate_notice_served and action_type in RETRY_ACTIONS:
        return GuardrailCheck(
            risk_id=risk_id,
            action_index=action_index,
            result=GuardrailResultEnum.BLOCK,
            reason="mandate_notice_required",
            checked_at=checked_at,
        )

    # 3. cooldown_active
    if ctx.last_retry_at is not None and action_type in RETRY_ACTIONS:
        elapsed = (ctx.current_time - ctx.last_retry_at).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            return GuardrailCheck(
                risk_id=risk_id,
                action_index=action_index,
                result=GuardrailResultEnum.BLOCK,
                reason="cooldown_active",
                checked_at=checked_at,
            )

    # 4. dnd_hours (customer-facing actions only allowed 09:00 to 20:00)
    if action_type in CUSTOMER_FACING_ACTIONS:
        current_hour = ctx.current_time.hour
        # Outside 9:00 AM (inclusive) to 8:00 PM (exclusive)
        if current_hour < DND_START_HOUR or current_hour >= DND_END_HOUR:
            return GuardrailCheck(
                risk_id=risk_id,
                action_index=action_index,
                result=GuardrailResultEnum.BLOCK,
                reason="dnd_hours",
                checked_at=checked_at,
            )

    # 5. customer_opted_out
    if ctx.customer_opted_out and action_type in CUSTOMER_FACING_ACTIONS:
        return GuardrailCheck(
            risk_id=risk_id,
            action_index=action_index,
            result=GuardrailResultEnum.BLOCK,
            reason="customer_opted_out",
            checked_at=checked_at,
        )

    # 6. amount_requires_human_approval
    if amount > ctx.human_approval_threshold:
        return GuardrailCheck(
            risk_id=risk_id,
            action_index=action_index,
            result=GuardrailResultEnum.BLOCK,
            reason="amount_requires_human_approval",
            checked_at=checked_at,
        )

    # All guardrails passed
    return GuardrailCheck(
        risk_id=risk_id,
        action_index=action_index,
        result=GuardrailResultEnum.PASS,
        reason=None,
        checked_at=checked_at,
    )


from src.audit import log_audit


def evaluate_and_record_guardrails(
    conn: sqlite3.Connection,
    risk_id: str,
    amount: float,
    action_index: int,
    action_type: ActionType,
    context: Optional[GuardrailContext] = None,
) -> GuardrailCheck:
    """
    Evaluates guardrails, persists the check record in SQLite guardrail_checks table,
    and appends an immutable audit log entry.
    """
    check = evaluate_guardrails(
        risk_id=risk_id,
        amount=amount,
        action_index=action_index,
        action_type=action_type,
        context=context,
    )
    insert_guardrail_check(conn, check)

    decision = "guardrail_pass" if check.result == GuardrailResultEnum.PASS else "guardrail_block"
    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="guardrail",
        input_data={
            "action_index": action_index,
            "action_type": action_type.value,
            "amount": amount,
            "attempt_number": context.attempt_number if context else 1,
        },
        output_data=check,
        decision=decision,
    )

    return check
