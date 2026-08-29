import sqlite3
from typing import Dict, Any, List, Optional
from src.models import ActionType, RootCauseEnum, EventStatus, GuardrailResultEnum, ExecutionStatusEnum
from src.audit import get_audit_trail


def get_summary_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Computes overall KPI summary metrics from SQLite tables.
    """
    cursor = conn.cursor()

    # 1. Total revenue at risk & count
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0.0) FROM risk_events")
    row = cursor.fetchone()
    transactions_count = row[0] if row else 0
    total_revenue_at_risk = float(row[1]) if row else 0.0

    # 2. Total revenue recovered & recovered transactions count
    cursor.execute("""
        SELECT COUNT(DISTINCT risk_id), COALESCE(SUM(amount_recovered), 0.0)
        FROM outcomes
        WHERE result = 'SUCCESS'
    """)
    row = cursor.fetchone()
    recovered_count = row[0] if row else 0
    total_revenue_recovered = float(row[1]) if row else 0.0

    # 3. Recovery rate %
    recovery_rate_pct = round(
        (total_revenue_recovered / total_revenue_at_risk * 100.0) if total_revenue_at_risk > 0 else 0.0,
        2,
    )

    # 4. Failed recovery attempts (execution attempts that failed)
    cursor.execute("SELECT COUNT(*) FROM executions WHERE status = 'FAILED'")
    row = cursor.fetchone()
    failed_attempts_count = row[0] if row else 0

    # 5. Successful execution attempts
    cursor.execute("SELECT COUNT(*) FROM executions WHERE status = 'SUCCESS'")
    row = cursor.fetchone()
    successful_attempts_count = row[0] if row else 0

    # 6. Guardrail blocks count
    cursor.execute("SELECT COUNT(*) FROM guardrail_checks WHERE result = 'BLOCK'")
    row = cursor.fetchone()
    guardrail_blocks_count = row[0] if row else 0

    # 7. Escalations count
    cursor.execute("SELECT COUNT(*) FROM escalations")
    row = cursor.fetchone()
    escalations_count = row[0] if row else 0

    return {
        "total_revenue_at_risk": total_revenue_at_risk,
        "total_revenue_recovered": total_revenue_recovered,
        "recovery_rate_pct": recovery_rate_pct,
        "transactions_count": transactions_count,
        "recovered_count": recovered_count,
        "failed_attempts_count": failed_attempts_count,
        "successful_attempts_count": successful_attempts_count,
        "guardrail_blocks_count": guardrail_blocks_count,
        "escalations_count": escalations_count,
    }


def get_root_cause_breakdown(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Returns aggregation of risks, total amount at risk, and recovered amount per root cause.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            rc.root_cause,
            COUNT(DISTINCT re.risk_id) as count,
            COALESCE(SUM(re.amount), 0.0) as total_at_risk,
            COALESCE(SUM(CASE WHEN re.status = 'RECOVERED' THEN re.amount ELSE 0.0 END), 0.0) as recovered_amount
        FROM root_causes rc
        JOIN risk_events re ON rc.risk_id = re.risk_id
        GROUP BY rc.root_cause
        ORDER BY count DESC
    """)
    rows = cursor.fetchall()
    results = []
    for r in rows:
        at_risk = float(r["total_at_risk"])
        rec = float(r["recovered_amount"])
        rate = round((rec / at_risk * 100.0) if at_risk > 0 else 0.0, 1)
        results.append({
            "root_cause": r["root_cause"],
            "count": r["count"],
            "total_at_risk": at_risk,
            "recovered_amount": rec,
            "recovery_rate_pct": rate,
        })
    return results


def get_action_performance_breakdown(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Returns execution and recovery performance broken down by ActionType.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            e.action_type,
            COUNT(*) as attempts,
            SUM(CASE WHEN e.status = 'SUCCESS' THEN 1 ELSE 0 END) as successes,
            SUM(CASE WHEN e.status = 'FAILED' THEN 1 ELSE 0 END) as failures,
            COALESCE(SUM(CASE WHEN e.status = 'SUCCESS' THEN o.amount_recovered ELSE 0.0 END), 0.0) as recovered_amount
        FROM executions e
        LEFT JOIN outcomes o ON e.risk_id = o.risk_id AND e.action_index = o.action_index AND o.result = 'SUCCESS'
        GROUP BY e.action_type
        ORDER BY attempts DESC
    """)
    rows = cursor.fetchall()
    return [
        {
            "action_type": r["action_type"],
            "attempts": r["attempts"],
            "successes": r["successes"],
            "failures": r["failures"],
            "recovered_amount": float(r["recovered_amount"]),
        }
        for r in rows
    ]


def get_escalation_and_block_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Returns breakdown of reasons for escalations and guardrail blocks.
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT reason, COUNT(*) as count
        FROM escalations
        GROUP BY reason
        ORDER BY count DESC
    """)
    escalation_rows = cursor.fetchall()
    escalations_by_reason = [{"reason": r["reason"], "count": r["count"]} for r in escalation_rows]

    cursor.execute("""
        SELECT reason, COUNT(*) as count
        FROM guardrail_checks
        WHERE result = 'BLOCK'
        GROUP BY reason
        ORDER BY count DESC
    """)
    block_rows = cursor.fetchall()
    blocks_by_reason = [{"reason": r["reason"], "count": r["count"]} for r in block_rows]

    return {
        "escalations_by_reason": escalations_by_reason,
        "blocks_by_reason": blocks_by_reason,
    }


def get_transactions_list(conn: sqlite3.Connection, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Returns a list of all transactions with essential metadata for the UI table.
    """
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT 
            re.risk_id,
            re.event_id,
            re.risk_type,
            re.amount,
            re.priority,
            re.status,
            re.created_at,
            rc.root_cause,
            COALESCE(esc.reason, NULL) as escalation_reason,
            COALESCE((SELECT SUM(o.amount_recovered) FROM outcomes o WHERE o.risk_id = re.risk_id AND o.result = 'SUCCESS'), 0.0) as amount_recovered,
            (SELECT COUNT(*) FROM executions e WHERE e.risk_id = re.risk_id) as executions_count
        FROM risk_events re
        LEFT JOIN root_causes rc ON re.risk_id = rc.risk_id
        LEFT JOIN escalations esc ON re.risk_id = esc.risk_id
        ORDER BY re.created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    return [
        {
            "risk_id": r["risk_id"],
            "event_id": r["event_id"],
            "risk_type": r["risk_type"],
            "amount": float(r["amount"]),
            "priority": r["priority"],
            "status": r["status"],
            "created_at": r["created_at"],
            "root_cause": r["root_cause"],
            "escalation_reason": r["escalation_reason"],
            "amount_recovered": float(r["amount_recovered"]),
            "executions_count": r["executions_count"],
        }
        for r in rows
    ]


def get_transaction_detail(conn: sqlite3.Connection, risk_id: str) -> Optional[Dict[str, Any]]:
    """
    Returns complete transaction details and ordered audit trail for drill-down.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM risk_events WHERE risk_id = ?", (risk_id,))
    row = cursor.fetchone()
    if not row:
        return None

    audit_trail = get_audit_trail(conn, risk_id)
    return {
        "risk_id": row["risk_id"],
        "event_id": row["event_id"],
        "risk_type": row["risk_type"],
        "amount": float(row["amount"]),
        "priority": row["priority"],
        "status": row["status"],
        "created_at": row["created_at"],
        "audit_trail": [entry.model_dump(mode="json") for entry in audit_trail],
    }
