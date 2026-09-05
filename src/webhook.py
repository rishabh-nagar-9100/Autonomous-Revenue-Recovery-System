import json
import sqlite3
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

from src.models import WebhookProcessingStatus
from src.integrations.razorpay_client import RazorpayClientAdapter
from src.integrations.config import RAZORPAY_WEBHOOK_SECRET
from src.audit import log_audit


from src.integrations.config import get_razorpay_webhook_secret


def _safe_dict(obj: Any, key: str) -> Dict[str, Any]:
    """Safely extracts a nested dictionary from parent obj under key without throwing AttributeError."""
    if isinstance(obj, dict):
        val = obj.get(key)
        if isinstance(val, dict):
            return val
    return {}


def extract_reference_id(payload: Any) -> Optional[str]:
    """
    Pure, read-only, fail-safe provenance extractor for Razorpay webhook payloads.
    Safely inspects payment.entity.notes, order.entity.notes, order.entity.receipt,
    and payment_link.entity.reference_id / notes.
    
    Robustness guarantees:
    - Never raises an exception if 'notes' is dict, list, None, or any unexpected type.
    - If notes is a dict: reads reference_id / risk_id safely.
    - If notes is a list or None: treats as missing/unavailable metadata without calling .get().
    - Returns a validated non-empty risk ID string or None.
    """
    if not isinstance(payload, dict):
        return None

    def _is_valid_risk_id(val: Any) -> bool:
        if isinstance(val, str):
            cleaned = val.strip()
            if cleaned.startswith("risk_"):
                return True
        return False

    def _extract_from_notes(entity: Any) -> Optional[str]:
        if not isinstance(entity, dict):
            return None
        notes = entity.get("notes")
        if isinstance(notes, dict):
            for k in ("reference_id", "risk_id"):
                v = notes.get(k)
                if _is_valid_risk_id(v):
                    return str(v).strip()
        return None

    payload_data = _safe_dict(payload, "payload")
    payment_entity = _safe_dict(_safe_dict(payload_data, "payment"), "entity")
    order_entity = _safe_dict(_safe_dict(payload_data, "order"), "entity")
    payment_link_entity = _safe_dict(_safe_dict(payload_data, "payment_link"), "entity")

    # 1. Payment notes
    ref = _extract_from_notes(payment_entity)
    if ref:
        return ref

    # 2. Order notes
    ref = _extract_from_notes(order_entity)
    if ref:
        return ref

    # 3. Order receipt
    if isinstance(order_entity, dict):
        rcpt = order_entity.get("receipt")
        if _is_valid_risk_id(rcpt):
            return str(rcpt).strip()

    # 4. Payment Link reference_id
    if isinstance(payment_link_entity, dict):
        plink_ref = payment_link_entity.get("reference_id")
        if _is_valid_risk_id(plink_ref):
            return str(plink_ref).strip()

    # 5. Payment Link notes
    ref = _extract_from_notes(payment_link_entity)
    if ref:
        return ref

    # 6. Fallback: top-level payload notes if flattened
    ref = _extract_from_notes(payload)
    if ref:
        return ref

    # 7. Fallback: top-level reference_id / risk_id / receipt on payload
    for k in ("reference_id", "risk_id", "receipt"):
        v = payload.get(k)
        if _is_valid_risk_id(v):
            return str(v).strip()

    return None


def verify_webhook_signature(
    raw_body: str,
    signature: str,
    secret: Optional[str] = None,
) -> bool:
    """
    Verifies Razorpay webhook signature using HMAC-SHA256 HMAC digest comparison.
    """
    sec = secret or get_razorpay_webhook_secret()
    adapter = RazorpayClientAdapter(webhook_secret=sec)
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
        payload_data = _safe_dict(payload, "payload")
        payment_entity = _safe_dict(_safe_dict(payload_data, "payment"), "entity")
        order_entity = _safe_dict(_safe_dict(payload_data, "order"), "entity")
        payment_link_entity = _safe_dict(_safe_dict(payload_data, "payment_link"), "entity")

        candidate = extract_reference_id(payload)
        risk_id_target = candidate
        cursor = conn.cursor()
        found_in_db = False
        if risk_id_target:
            cursor.execute("SELECT 1 FROM risk_events WHERE risk_id = ?;", (risk_id_target,))
            if cursor.fetchone():
                found_in_db = True

        if not found_in_db and not risk_id_target:
            plink_id = payment_link_entity.get("id") if isinstance(payment_link_entity, dict) else None
            desc = payment_entity.get("description") if isinstance(payment_entity, dict) else None
            desc_token = desc.lstrip("#") if (isinstance(desc, str) and desc.startswith("#")) else (desc if isinstance(desc, str) else "")

            target_tokens = [t for t in [plink_id, desc_token] if t]
            for token in target_tokens:
                cursor.execute(
                    "SELECT risk_id FROM audit_log WHERE layer = 'action_executor' AND output_json LIKE ? ORDER BY id DESC LIMIT 1;",
                    (f"%{token}%",)
                )
                match_row = cursor.fetchone()
                if match_row:
                    risk_id_target = match_row["risk_id"] if hasattr(match_row, "keys") and "risk_id" in match_row.keys() else match_row[0]
                    found_in_db = True
                    break

        amount_val = 0.0
        if isinstance(payment_entity, dict) and payment_entity.get("amount"):
            amount_val = float(payment_entity["amount"]) / 100.0
        elif isinstance(order_entity, dict) and order_entity.get("amount_paid"):
            amount_val = float(order_entity["amount_paid"]) / 100.0
        elif isinstance(order_entity, dict) and order_entity.get("amount"):
            amount_val = float(order_entity["amount"]) / 100.0

        # 1. Log verified webhook receipt BEFORE subordinate reconciliation transitions
        audit_webhook_receipt = {
            "event_id": event_id,
            "event_name": event_name,
            "verification_source": "razorpay_webhook",
            "amount": amount_val,
        }
        payment_id = payment_entity.get("id") if isinstance(payment_entity, dict) else None
        order_id = order_entity.get("id") if isinstance(order_entity, dict) else None
        if payment_id:
            audit_webhook_receipt["razorpay_payment_id"] = payment_id
        if order_id:
            audit_webhook_receipt["order_id"] = order_id

        provenance_category = (
            "unattributed"
            if not risk_id_target
            else ("live" if risk_id_target.startswith("risk_live_") else "synthetic")
        )

        log_audit(
            conn=conn,
            risk_id=risk_id_target or "unattributed_webhook",
            layer="webhook_processor",
            input_data=audit_webhook_receipt,
            output_data={
                "status": "signature_verified",
                "risk_id": risk_id_target,
                "event_type": event_name,
                "provenance": provenance_category,
            },
            decision="webhook_received" if risk_id_target else "unattributed_webhook_quarantined",
        )

        if event_name in {"payment.captured", "payment_link.paid", "order.paid"}:
            from src.reconciliation import reconcile_payment_status
            if risk_id_target:
                reconcile_payment_status(
                    conn,
                    risk_id_target,
                    forced_status="RECOVERED",
                    amount=amount_val,
                    source_event=event_name,
                    razorpay_payment_id=payment_id,
                    webhook_event_id=event_id,
                    verification_source="razorpay_webhook",
                )
        elif event_name == "payment.authorized":
            from src.reconciliation import reconcile_payment_status
            if risk_id_target:
                reconcile_payment_status(
                    conn,
                    risk_id_target,
                    forced_status="AUTHORIZED",
                    amount=amount_val,
                    source_event=event_name,
                    razorpay_payment_id=payment_id,
                    webhook_event_id=event_id,
                    verification_source="razorpay_webhook",
                )
        elif event_name == "payment.failed":
            from src.reconciliation import reconcile_payment_status
            if risk_id_target:
                reconcile_payment_status(
                    conn,
                    risk_id_target,
                    forced_status="FAILED",
                    source_event=event_name,
                    razorpay_payment_id=payment_id,
                    webhook_event_id=event_id,
                    verification_source="razorpay_webhook",
                )

        # Transition to PROCESSED state
        update_webhook_status(conn, event_id, status=WebhookProcessingStatus.PROCESSED)

        log_audit(
            conn=conn,
            risk_id=risk_id_target or "unattributed_webhook",
            layer="webhook_processor",
            input_data={
                "event_id": event_id,
                "event_name": event_name,
                "razorpay_payment_id": payment_id,
            },
            output_data={"status": "processed", "provenance": provenance_category},
            decision="webhook_processed_successfully" if risk_id_target else "unattributed_webhook_quarantined",
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
