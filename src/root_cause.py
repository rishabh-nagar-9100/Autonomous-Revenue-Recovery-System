from typing import Optional, Any
from src.models import NormalizedEvent, RiskEvent, RootCause, RootCauseEnum
from src.llm import diagnose_root_cause_llm


# Deterministic mapping sets for error codes and reasons
BANK_TIMEOUT_REASONS = {
    "payment_timed_out",
    "gateway_timeout",
    "bank_timeout",
    "network_error",
    "bank_technical_error",
    "bank_unavailable",
    "payment_processing_error",
    "gateway_error",
}

BANK_TIMEOUT_CODES = {
    "GATEWAY_ERROR",
    "BAD_REQUEST_PAYMENT_TIMED_OUT",
    "GATEWAY_TIMEOUT",
    "BANK_TECHNICAL_ERROR",
    "SERVER_ERROR",
    "BANK_OFFLINE",
}

NSF_REASONS = {
    "insufficient_funds",
    "payment_cancelled_due_to_insufficient_funds",
    "nsf",
    "low_balance",
    "exceeds_balance",
    "account_insufficient_funds",
}

NSF_CODES = {
    "BAD_REQUEST_PAYMENT_FAILED_DUE_TO_INSUFFICIENT_FUNDS",
    "INSUFFICIENT_FUNDS",
    "PAYMENT_FAILED_LOW_BALANCE",
}

EXPIRED_CARD_REASONS = {
    "card_expired",
    "expired_card",
    "invalid_expiry_date",
    "expired_token",
    "card_validity_expired",
}

EXPIRED_CARD_CODES = {
    "BAD_REQUEST_PAYMENT_CARD_EXPIRED",
    "EXPIRED_CARD",
    "CARD_EXPIRED",
}


def diagnose_root_cause_rules(event: NormalizedEvent, risk_event: RiskEvent) -> RootCause:
    """
    Tier 1 Deterministic rule-based Root Cause Engine.
    Maps Razorpay error codes, reasons, and event metadata to fixed root cause enums.
    Returns UNKNOWN if signals are missing or unmapped.
    """
    # 1. Check for chronic non-payer flags in metadata first
    consecutive_failures = event.metadata.get("consecutive_failures", 0)
    is_chronic = (
        event.metadata.get("is_chronic_defaulter", False)
        or event.metadata.get("customer_risk_profile") == "chronic_non_payer"
        or consecutive_failures >= 4
    )
    if is_chronic:
        return RootCause(
            risk_id=risk_event.risk_id,
            root_cause=RootCauseEnum.CHRONIC_NON_PAYER,
            confidence=1.0,
            source="rule",
        )

    # 2. Check error_reason and error_code
    reason = (event.error_reason or "").strip().lower()
    code = (event.error_code or "").strip().upper()
    description = (event.error_description or "").strip().lower()

    # Bank Timeout
    if reason in BANK_TIMEOUT_REASONS or code in BANK_TIMEOUT_CODES:
        return RootCause(
            risk_id=risk_event.risk_id,
            root_cause=RootCauseEnum.BANK_TIMEOUT,
            confidence=1.0,
            source="rule",
        )

    # NSF (Insufficient Funds)
    if reason in NSF_REASONS or code in NSF_CODES:
        return RootCause(
            risk_id=risk_event.risk_id,
            root_cause=RootCauseEnum.NSF,
            confidence=1.0,
            source="rule",
        )

    # Expired Card
    if reason in EXPIRED_CARD_REASONS or code in EXPIRED_CARD_CODES:
        return RootCause(
            risk_id=risk_event.risk_id,
            root_cause=RootCauseEnum.EXPIRED_CARD,
            confidence=1.0,
            source="rule",
        )

    # Cart Abandonment
    if event.event_type == "cart_abandonment" or reason in {"cart_abandoned", "checkout_dropoff"} or code in {"CHECKOUT_DROPOFF", "CART_ABANDONMENT"}:
        return RootCause(
            risk_id=risk_event.risk_id,
            root_cause=RootCauseEnum.CART_ABANDONMENT,
            confidence=1.0,
            source="rule",
        )

    # Recent Overdue
    if event.event_type == "recent_overdue" or reason in {"invoice_overdue_1_day", "recent_overdue"} or code in {"INVOICE_OVERDUE", "RECENT_OVERDUE"}:
        return RootCause(
            risk_id=risk_event.risk_id,
            root_cause=RootCauseEnum.RECENT_OVERDUE,
            confidence=1.0,
            source="rule",
        )

    # Chronic Non Payer by reason/code
    if reason in {"chronic_defaulter", "chronic_non_payer"} or code in {"CHRONIC_NON_PAYER", "HIGH_RISK_USER"}:
        return RootCause(
            risk_id=risk_event.risk_id,
            root_cause=RootCauseEnum.CHRONIC_NON_PAYER,
            confidence=1.0,
            source="rule",
        )

    # Unmapped/unknown error
    return RootCause(
        risk_id=risk_event.risk_id,
        root_cause=RootCauseEnum.UNKNOWN,
        confidence=0.0,
        source="rule",
    )


def diagnose_root_cause(
    event: NormalizedEvent,
    risk_event: RiskEvent,
    use_llm_fallback: bool = True,
    llm_client: Optional[Any] = None,
) -> RootCause:
    """
    Tiered Root Cause Engine:
    Tier 1 (Deterministic): Rules engine. If known, source='rule' and LLM is NOT called.
    Tier 2 (LLM Fallback): If Tier 1 is UNKNOWN and fallback is enabled, queries LLM.
    If LLM returns a valid fixed enum -> source='llm'.
    If LLM fails/times out/returns invalid -> source='rule_fallback', root_cause=UNKNOWN.
    """
    # Tier 1: Deterministic rules
    rule_diagnosis = diagnose_root_cause_rules(event, risk_event)
    if rule_diagnosis.root_cause != RootCauseEnum.UNKNOWN:
        return rule_diagnosis

    # Tier 2: LLM Fallback
    if use_llm_fallback:
        llm_res = diagnose_root_cause_llm(event, risk_event, client=llm_client)
        if llm_res is not None and llm_res.root_cause != RootCauseEnum.UNKNOWN:
            return RootCause(
                risk_id=risk_event.risk_id,
                root_cause=llm_res.root_cause,
                confidence=llm_res.confidence,
                source="llm",
            )

    # Safe deterministic fallback
    return RootCause(
        risk_id=risk_event.risk_id,
        root_cause=RootCauseEnum.UNKNOWN,
        confidence=0.0,
        source="rule_fallback" if use_llm_fallback else "rule",
    )
