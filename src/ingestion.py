from typing import Dict, Any
from datetime import datetime
from src.models import NormalizedEvent


def normalize_payment_failed_event(raw_event: Dict[str, Any]) -> NormalizedEvent:
    """
    Normalizes raw payment_failed event payloads (Razorpay webhook format or direct dictionary format)
    into a standardized NormalizedEvent model.
    """
    if not isinstance(raw_event, dict):
        raise ValueError("Event payload must be a dictionary.")

    # Check if standard Razorpay webhook structure
    if "payload" in raw_event and "payment" in raw_event["payload"]:
        payment_entity = raw_event["payload"]["payment"].get("entity", {})
        if not payment_entity:
            raise ValueError("Malformed Razorpay webhook: missing payment.entity.")

        event_id = payment_entity.get("id")
        if not event_id:
            raise ValueError("Payment entity missing 'id'.")

        raw_amount = payment_entity.get("amount")
        if raw_amount is None:
            raise ValueError("Payment entity missing 'amount'.")

        # Razorpay amounts in webhook entity are usually in paise
        try:
            amount = float(raw_amount) / 100.0 if isinstance(raw_amount, int) else float(raw_amount)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid amount format: {raw_amount}")

        currency = payment_entity.get("currency", "INR")
        customer_id = (
            payment_entity.get("customer_id")
            or payment_entity.get("contact")
            or payment_entity.get("email")
            or "unknown_customer"
        )
        error_code = payment_entity.get("error_code")
        error_description = payment_entity.get("error_description")
        error_source = payment_entity.get("error_source")
        error_reason = payment_entity.get("error_reason")
        created_at_epoch = payment_entity.get("created_at")

        timestamp = (
            datetime.utcfromtimestamp(created_at_epoch)
            if created_at_epoch
            else datetime.utcnow()
        )

        metadata = {
            k: v
            for k, v in payment_entity.items()
            if k not in {"id", "amount", "currency", "customer_id", "error_code", "error_description", "error_source", "error_reason"}
        }

        return NormalizedEvent(
            event_id=event_id,
            event_type="payment_failed",
            amount=amount,
            currency=currency,
            customer_id=customer_id,
            error_code=error_code,
            error_description=error_description,
            error_source=error_source,
            error_reason=error_reason,
            metadata=metadata,
            timestamp=timestamp,
        )

    # Direct / simplified event structure
    event_id = raw_event.get("event_id") or raw_event.get("id")
    if not event_id:
        raise ValueError("Event missing 'event_id' or 'id'.")

    raw_amount = raw_event.get("amount")
    if raw_amount is None:
        raise ValueError("Event missing 'amount'.")

    try:
        amount = float(raw_amount)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid amount format: {raw_amount}")

    event_type = raw_event.get("event_type") or raw_event.get("event", "payment_failed")
    currency = raw_event.get("currency", "INR")
    customer_id = raw_event.get("customer_id", "unknown_customer")
    error_code = raw_event.get("error_code")
    error_description = raw_event.get("error_description")
    error_source = raw_event.get("error_source")
    error_reason = raw_event.get("error_reason")
    metadata = raw_event.get("metadata", {})

    return NormalizedEvent(
        event_id=event_id,
        event_type=event_type,
        amount=amount,
        currency=currency,
        customer_id=customer_id,
        error_code=error_code,
        error_description=error_description,
        error_source=error_source,
        error_reason=error_reason,
        metadata=metadata,
        timestamp=raw_event.get("timestamp") or datetime.utcnow(),
    )
