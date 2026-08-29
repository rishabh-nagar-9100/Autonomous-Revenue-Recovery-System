import json
import sqlite3
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

from src.models import WebhookProcessingStatus
from src.integrations.razorpay_client import RazorpayClientAdapter
from src.integrations.config import RAZORPAY_WEBHOOK_SECRET
from src.audit import log_audit


def verify_webhook_signature(
    raw_body: str,
    signature: str,
    secret: Optional[str] = None,
) -> bool:
    """
    Verifies Razorpay webhook signature using HMAC-SHA256 HMAC digest comparison.
    """
    adapter = RazorpayClientAdapter(webhook_secret=secret or RAZORPAY_WEBHOOK_SECRET)
    return adapter.verify_webhook_signature(raw_body, signature)


def extract_event_id(headers: Dict[str, str], payload: Dict[str, Any]) -> str:
    """
    Extracts unique event ID from HTTP headers (x-razorpay-event-id) or payload entity.
    """
    header_event_id = headers.get("x-razorpay-event-id") or headers.get("X-Razorpay-Event-Id")
    if header_event_id:
        return header_event_id

    # Check payload entity ID or top-level event ID
    if isinstance(payload, dict):
        if "event_id" in payload:
            return str(payload["event_id"])
        if "id" in payload:
            return str(payload["id"])
        if "payload" in payload and isinstance(payload["payload"], dict):
            payment_entity = payload["payload"].get("payment", {}).get("entity", {})
            if "id" in payment_entity:
                return f"evt_{payment_entity['id']}"

    # Fallback to generated hash if payload exists
    import hashlib
    raw_str = json.dumps(payload, sort_keys=True)
    return f"evt_hash_{hashlib.md5(raw_str.encode('utf-8')).hexdigest()[:16]}"


def is_duplicate_event(conn: sqlite3.Connection, event_id: str) -> bool:
    """Checks whether a webhook event has already been recorded in webhook_events table."""
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM webhook_events WHERE event_id = ?;", (event_id,))
    return cursor.fetchone() is not None


def record_webhook_event(
    conn: sqlite3.Connection,
    event_id: str,
    raw_payload: str,
    status: WebhookProcessingStatus = WebhookProcessingStatus.RECEIVED,
) -> None:
    """Records a new webhook event row in webhook_events table."""
    with conn:
        conn.execute(
            """
            INSERT INTO webhook_events (event_id, received_at, raw_payload, processing_status)
            VALUES (?, ?, ?, ?);
            """,
            (event_id, datetime.utcnow().isoformat(), raw_payload, status.value),
        )


def update_webhook_status(
    conn: sqlite3.Connection,
    event_id: str,
    status: WebhookProcessingStatus,
    error_reason: Optional[str] = None,
) -> None:
    """Updates processing lifecycle status and timestamp for a webhook event."""
    with conn:
        conn.execute(
            """
            UPDATE webhook_events
            SET processing_status = ?, processed_at = ?, error_reason = ?
            WHERE event_id = ?;
            """,
            (
                status.value,
                datetime.utcnow().isoformat() if status in {WebhookProcessingStatus.PROCESSED, WebhookProcessingStatus.FAILED} else None,
                error_reason,
                event_id,
            ),
        )


def process_webhook(
    conn: sqlite3.Connection,
    raw_body: str,
    headers: Dict[str, str],
    webhook_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Complete webhook ingestion, signature verification, deduplication, and lifecycle processing pipeline.
    Lifecycle states: RECEIVED -> PROCESSING -> PROCESSED | FAILED
    """
    signature = headers.get("x-razorpay-signature") or headers.get("X-Razorpay-Signature") or ""

    # Signature verification
    if not verify_webhook_signature(raw_body, signature, secret=webhook_secret):
        raise ValueError("Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON webhook payload: {str(err)}") from err

    event_id = extract_event_id(headers, payload)

    # Event-ID Deduplication (Idempotency check)
    if is_duplicate_event(conn, event_id):
        log_audit(
            conn=conn,
            risk_id="system_webhook",
            layer="webhook_processor",
            input_data={"event_id": event_id},
            output_data={"status": "duplicate_skipped"},
            decision="duplicate_event_ignored",
        )
        return {
            "status": "duplicate_skipped",
            "event_id": event_id,
            "message": "Duplicate webhook event acknowledged without re-processing.",
        }

    # Record INITIAL RECEIVED state
    record_webhook_event(conn, event_id, raw_body, status=WebhookProcessingStatus.RECEIVED)

    # Transition to PROCESSING state
    update_webhook_status(conn, event_id, status=WebhookProcessingStatus.PROCESSING)

    try:
        # Business logic processing of webhook event
        event_name = payload.get("event", "payment.failed")
        risk_id_target = None

        # Reconcile or process payment status
        if "payload" in payload and "payment" in payload["payload"]:
            payment_entity = payload["payload"]["payment"].get("entity", {})
            risk_id_target = payment_entity.get("notes", {}).get("reference_id") or payment_entity.get("id")

            if event_name in {"payment.captured", "payment_link.paid"}:
                from src.reconciliation import reconcile_payment_status
                if risk_id_target:
                    reconcile_payment_status(
                        conn,
                        risk_id_target,
                        forced_status="RECOVERED",
                        amount=float(payment_entity.get("amount", 0)) / 100.0 if payment_entity.get("amount") else 0.0,
                    )
            elif event_name == "payment.authorized":
                from src.reconciliation import reconcile_payment_status
                if risk_id_target:
                    reconcile_payment_status(
                        conn,
                        risk_id_target,
                        forced_status="AUTHORIZED",
                        amount=float(payment_entity.get("amount", 0)) / 100.0 if payment_entity.get("amount") else 0.0,
                    )
            elif event_name == "payment.failed":
                from src.reconciliation import reconcile_payment_status
                if risk_id_target:
                    reconcile_payment_status(
                        conn,
                        risk_id_target,
                        forced_status="FAILED",
                    )

        # Transition to PROCESSED state
        update_webhook_status(conn, event_id, status=WebhookProcessingStatus.PROCESSED)

        log_audit(
            conn=conn,
            risk_id=risk_id_target or "system_webhook",
            layer="webhook_processor",
            input_data={"event_id": event_id, "event_name": event_name},
            output_data={"status": "processed"},
            decision="webhook_processed_successfully",
        )

        return {
            "status": "processed",
            "event_id": event_id,
            "event_name": event_name,
        }

    except Exception as exc:
        update_webhook_status(conn, event_id, status=WebhookProcessingStatus.FAILED, error_reason=str(exc))
        log_audit(
            conn=conn,
            risk_id="system_webhook",
            layer="webhook_processor",
            input_data={"event_id": event_id},
            output_data={"error": str(exc)},
            decision="webhook_processing_failed",
        )
        raise exc
