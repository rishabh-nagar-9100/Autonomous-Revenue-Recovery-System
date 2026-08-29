import json
from typing import Any, Optional, List
from datetime import datetime, date
import sqlite3
from pydantic import BaseModel
from src.models import AuditLogEntry
from src.db import insert_audit_log, get_audit_trail_for_risk


def _to_json_serializable(obj: Any) -> Any:
    """Converts objects, Pydantic models, enums, and datetimes to JSON-compatible data."""
    if obj is None:
        return None
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if hasattr(obj, "value"):  # Enum
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_json_serializable(item) for item in obj]
    return obj


def log_audit(
    conn: sqlite3.Connection,
    risk_id: str,
    layer: str,
    input_data: Any,
    output_data: Any,
    decision: str,
    timestamp: Optional[datetime] = None,
) -> AuditLogEntry:
    """
    Appends an immutable audit entry for a state transition in the recovery workflow.
    """
    ts = timestamp or datetime.utcnow()
    input_serializable = _to_json_serializable(input_data)
    output_serializable = _to_json_serializable(output_data)

    input_json = json.dumps(input_serializable, default=str)
    output_json = json.dumps(output_serializable, default=str)

    entry = AuditLogEntry(
        id=None,
        risk_id=risk_id,
        layer=layer,
        input_json=input_json,
        output_json=output_json,
        decision=decision,
        timestamp=ts,
    )

    row_id = insert_audit_log(conn, entry)
    entry.id = row_id
    return entry


def get_audit_trail(conn: sqlite3.Connection, risk_id: str) -> List[AuditLogEntry]:
    """
    Retrieves the complete, chronological audit history for a single risk_id.
    """
    return get_audit_trail_for_risk(conn, risk_id)
