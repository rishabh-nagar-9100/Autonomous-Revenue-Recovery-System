import sqlite3
from typing import Dict, Any, Tuple, Optional
from src.models import NormalizedEvent, RiskEvent, RootCause
from src.ingestion import normalize_payment_failed_event
from src.risk_detector import detect_revenue_risk
from src.root_cause import diagnose_root_cause
from src.db import insert_risk_event, insert_root_cause
from src.audit import log_audit


def process_payment_failed_event(
    raw_event: Dict[str, Any],
    conn: sqlite3.Connection,
    use_llm_fallback: bool = True,
    llm_client: Optional[Any] = None,
) -> Tuple[NormalizedEvent, RiskEvent, RootCause]:
    """
    Pipeline Coordinator:
    1. Normalizes raw payment_failed event payload and logs audit.
    2. Detects revenue risk, constructs RiskEvent, and logs audit.
    3. Diagnoses root cause via Tier 1 Rules + Tier 2 LLM fallback, and logs audit.
    4. Persists RiskEvent and RootCause to SQLite database.
    """
    # 1. Ingestion & Normalization
    normalized = normalize_payment_failed_event(raw_event)

    # 2. Revenue Risk Detection
    risk_event = detect_revenue_risk(normalized)

    # Ingestion audit log
    log_audit(
        conn=conn,
        risk_id=risk_event.risk_id,
        layer="ingestion",
        input_data=raw_event,
        output_data=normalized,
        decision="event_normalized",
    )

    # Risk detection audit log
    log_audit(
        conn=conn,
        risk_id=risk_event.risk_id,
        layer="revenue_risk_detector",
        input_data=normalized,
        output_data=risk_event,
        decision="revenue_at_risk_detected",
    )

    # 3. Tiered Root Cause Diagnosis (Tier 1 rules first; Tier 2 LLM if unknown)
    root_cause = diagnose_root_cause(
        event=normalized,
        risk_event=risk_event,
        use_llm_fallback=use_llm_fallback,
        llm_client=llm_client,
    )

    # Root cause diagnosis audit log
    log_audit(
        conn=conn,
        risk_id=risk_event.risk_id,
        layer="root_cause_engine",
        input_data=risk_event,
        output_data=root_cause,
        decision="root_cause_identified",
    )

    # 4. Database Persistence
    insert_risk_event(conn, risk_event)
    insert_root_cause(conn, root_cause)

    return normalized, risk_event, root_cause
