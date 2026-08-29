import uuid
from src.models import NormalizedEvent, RiskEvent, RiskType, Priority, EventStatus


def detect_revenue_risk(event: NormalizedEvent) -> RiskEvent:
    """
    Rule-based Revenue Risk Detector.
    Evaluates normalized event to assess risk type, amount at risk, priority, and initial status.
    """
    # Deterministic priority classification rules based on transaction value & metadata
    is_vip = event.metadata.get("is_vip", False) or event.metadata.get("customer_tier") == "vip"
    
    if event.amount >= 10000.0 or is_vip:
        priority = Priority.HIGH
    elif event.amount >= 2500.0:
        priority = Priority.MEDIUM
    else:
        priority = Priority.LOW

    # Map event_type to RiskType
    if event.event_type == "payment_failed":
        risk_type = RiskType.PAYMENT_FAILED
    elif event.event_type == "cart_abandonment":
        risk_type = RiskType.CART_ABANDONMENT
    elif event.event_type == "recent_overdue":
        risk_type = RiskType.RECENT_OVERDUE
    else:
        risk_type = RiskType.PAYMENT_FAILED

    risk_id = f"risk_{event.event_id}"

    return RiskEvent(
        risk_id=risk_id,
        event_id=event.event_id,
        risk_type=risk_type,
        amount=event.amount,
        priority=priority,
        status=EventStatus.DETECTED,
        created_at=event.timestamp,
    )
