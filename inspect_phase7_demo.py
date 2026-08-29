import sqlite3
import json
from src.db import init_db, get_db_connection
from src.batch_runner import generate_synthetic_batch, run_synthetic_batch
from src.metrics import (
    get_summary_metrics,
    get_root_cause_breakdown,
    get_action_performance_breakdown,
    get_escalation_and_block_summary,
    get_transactions_list,
    get_transaction_detail,
)


def run_demo():
    conn = sqlite3.connect("recovery.db")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # Clear previous runs
    with conn:
        conn.execute("DELETE FROM audit_log;")
        conn.execute("DELETE FROM outcomes;")
        conn.execute("DELETE FROM escalations;")
        conn.execute("DELETE FROM executions;")
        conn.execute("DELETE FROM guardrail_checks;")
        conn.execute("DELETE FROM interventions;")
        conn.execute("DELETE FROM root_causes;")
        conn.execute("DELETE FROM risk_events;")

    print("=" * 80)
    print("RUNNING SYNTHETIC BATCH OF 60 EVENTS...")
    print("=" * 80)
    batch = generate_synthetic_batch(60)
    batch_res = run_synthetic_batch(conn=conn, batch=batch)
    print(f"Successfully processed {batch_res['total_processed']} events through the recovery pipeline.\n")

    # 1. Summary Metrics
    print("=" * 80)
    print("1. SUMMARY METRICS (GET /api/metrics)")
    print("=" * 80)
    metrics = get_summary_metrics(conn)
    print(json.dumps(metrics, indent=2))

    # 2. Root Cause Breakdown
    print("\n" + "=" * 80)
    print("2. ROOT CAUSE BREAKDOWN (GET /api/breakdown/root-cause)")
    print("=" * 80)
    rc_breakdown = get_root_cause_breakdown(conn)
    print(json.dumps(rc_breakdown, indent=2))

    # 3. Action Performance Breakdown
    print("\n" + "=" * 80)
    print("3. ACTION PERFORMANCE BREAKDOWN (GET /api/breakdown/actions)")
    print("=" * 80)
    actions_breakdown = get_action_performance_breakdown(conn)
    print(json.dumps(actions_breakdown, indent=2))

    # 4. Escalations and Block Summary
    print("\n" + "=" * 80)
    print("4. COMPLIANCE & ESCALATION SUMMARY (GET /api/breakdown/escalations)")
    print("=" * 80)
    esc_summary = get_escalation_and_block_summary(conn)
    print(json.dumps(esc_summary, indent=2))

    # 5. Recovered Transaction Drill-Down
    txs = get_transactions_list(conn, limit=100)
    rec_tx = next((t for t in txs if t["status"] == "RECOVERED" and t["amount_recovered"] > 0), None)
    if rec_tx:
        print("\n" + "=" * 80)
        print(f"5. RECOVERED TRANSACTION DRILL-DOWN: {rec_tx['risk_id']}")
        print("=" * 80)
        rec_detail = get_transaction_detail(conn, rec_tx["risk_id"])
        print(f"Amount: ₹{rec_detail['amount']} | Priority: {rec_detail['priority']} | Status: {rec_detail['status']}")
        print("Audit Trail Transitions:")
        for e in rec_detail["audit_trail"]:
            print(f"  [{e['layer']:<22}] {e['decision']:<26} ({e['timestamp']})")

    # 6. Blocked & Escalated Transaction Drill-Down
    block_tx = next((t for t in txs if t["status"] == "ESCALATED" and t.get("escalation_reason", "").startswith("guardrail_blocked")), None)
    if block_tx:
        print("\n" + "=" * 80)
        print(f"6. BLOCKED & ESCALATED TRANSACTION DRILL-DOWN: {block_tx['risk_id']}")
        print("=" * 80)
        block_detail = get_transaction_detail(conn, block_tx["risk_id"])
        print(f"Amount: ₹{block_detail['amount']} | Priority: {block_detail['priority']} | Status: {block_detail['status']}")
        print("Audit Trail Transitions:")
        for e in block_detail["audit_trail"]:
            print(f"  [{e['layer']:<22}] {e['decision']:<26} ({e['timestamp']})")

    conn.close()


if __name__ == "__main__":
    run_demo()
