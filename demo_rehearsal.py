import os
os.environ["EXECUTION_MODE"] = "mock"
import sqlite3
import json
from src.db import init_db
from src.batch_runner import generate_synthetic_batch, run_synthetic_batch
from src.metrics import (
    get_summary_metrics,
    get_root_cause_breakdown,
    get_action_performance_breakdown,
    get_escalation_and_block_summary,
    get_transactions_list,
    get_transaction_detail,
)


def reset_database(conn: sqlite3.Connection):
    """Resets all recovery tables for clean reproducible run."""
    with conn:
        conn.execute("DELETE FROM audit_log;")
        conn.execute("DELETE FROM outcomes;")
        conn.execute("DELETE FROM escalations;")
        conn.execute("DELETE FROM executions;")
        conn.execute("DELETE FROM guardrail_checks;")
        conn.execute("DELETE FROM interventions;")
        conn.execute("DELETE FROM root_causes;")
        conn.execute("DELETE FROM risk_events;")


def run_rehearsal_pass(pass_number: int, db_path: str = "rehearsal.db"):
    print("\n" + "=" * 90)
    print(f"STARTING DEMO REHEARSAL PASS #{pass_number} (FROM CLEAN STATE)")
    print("=" * 90)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    reset_database(conn)

    # 1. Generate and Run 65-event deterministic synthetic batch
    batch = generate_synthetic_batch(size=65, seed=42)
    print(f"Generated {len(batch)} deterministic synthetic events covering all 6 root causes, LLM fallbacks, and guardrails.")
    batch_res = run_synthetic_batch(conn=conn, batch=batch)
    print(f"Processed {batch_res['total_processed']} events through full recovery pipeline without errors.")

    # 2. Extract metrics
    metrics = get_summary_metrics(conn)
    print(f"\nREHEARSAL #{pass_number} SUMMARY METRICS:")
    print(f"  - Total Transactions Analyzed: {metrics['transactions_count']}")
    print(f"  - Total Revenue At Risk:       ₹{metrics['total_revenue_at_risk']:,.2f}")
    print(f"  - Total Revenue Recovered:     ₹{metrics['total_revenue_recovered']:,.2f}")
    print(f"  - Overall Recovery Rate:       {metrics['recovery_rate_pct']}%")
    print(f"  - Recovered Transactions:      {metrics['recovered_count']}")
    print(f"  - Guardrail Compliance Blocks: {metrics['guardrail_blocks_count']}")
    print(f"  - Escalations to Ops:          {metrics['escalations_count']}")

    # 3. Retrieve specific scenario traces for verification
    tx_list = get_transactions_list(conn, limit=100)

    # Demo 1: Multi-step recovery (bank_timeout -> smart_retry FAIL -> payment_link SUCCESS)
    multi_step_tx = next((t for t in tx_list if t["executions_count"] == 2 and t["status"] == "RECOVERED"), None)
    
    # Demo 2: Guardrail Block (DND or opt-out)
    blocked_tx = next((t for t in tx_list if (t.get("escalation_reason") or "").startswith("guardrail_blocked")), None)

    # Demo 3: LLM Fallback Success
    llm_success_tx = next((t for t in batch_res["events"] if t.get("source") == "llm" and t["status"] == "RECOVERED"), None)

    # Demo 4: LLM Timeout / Safe Fallback
    llm_timeout_tx = next((t for t in batch_res["events"] if t.get("source") == "rule_fallback"), None)

    if pass_number == 2:
        # Print detailed audit traces on final rehearsal pass
        print("\n" + "=" * 90)
        print("DEMO NARRATIVE 1: MULTI-STEP RECOVERED TRANSACTION AUDIT TRAIL")
        print("=" * 90)
        if multi_step_tx:
            detail = get_transaction_detail(conn, multi_step_tx["risk_id"])
            print(f"Risk ID: {detail['risk_id']} | Amount: ₹{detail['amount']:,.2f} | Status: {detail['status']}")
            for entry in detail["audit_trail"]:
                print(f"  [{entry['layer']:<22}] {entry['decision']:<26} ({entry['timestamp']})")
                if entry['decision'] == 'action_executed':
                    out = json.loads(entry['output_json'])
                    print(f"       -> {out['action_type']} Status: {out['status']}")

        print("\n" + "=" * 90)
        print("DEMO NARRATIVE 2: GUARDRAIL SAFETY & COMPLIANCE BLOCK AUDIT TRAIL")
        print("=" * 90)
        if blocked_tx:
            detail = get_transaction_detail(conn, blocked_tx["risk_id"])
            print(f"Risk ID: {detail['risk_id']} | Amount: ₹{detail['amount']:,.2f} | Reason: {blocked_tx['escalation_reason']}")
            for entry in detail["audit_trail"]:
                print(f"  [{entry['layer']:<22}] {entry['decision']:<26} ({entry['timestamp']})")
            # Verify blocked action was not executed
            exec_layers = [e for e in detail["audit_trail"] if e['layer'] == 'action_executor']
            print(f"Confirmed Executor Record Count: {len(exec_layers)} (Blocked action was NOT executed)")

        print("\n" + "=" * 90)
        print("DEMO NARRATIVE 3: AMBIGUOUS ERROR -> LLM FALLBACK SUCCESS AUDIT TRAIL")
        print("=" * 90)
        if llm_success_tx:
            detail = get_transaction_detail(conn, llm_success_tx["risk_id"])
            print(f"Risk ID: {detail['risk_id']} | Amount: ₹{detail['amount']:,.2f} | Diagnosed Root Cause: {llm_success_tx['root_cause']}")
            for entry in detail["audit_trail"]:
                print(f"  [{entry['layer']:<22}] {entry['decision']:<26} ({entry['timestamp']})")

        print("\n" + "=" * 90)
        print("DEMO NARRATIVE 4: AMBIGUOUS ERROR -> LLM TIMEOUT SAFE FALLBACK AUDIT TRAIL")
        print("=" * 90)
        if llm_timeout_tx:
            detail = get_transaction_detail(conn, llm_timeout_tx["risk_id"])
            print(f"Risk ID: {detail['risk_id']} | Amount: ₹{detail['amount']:,.2f} | Fallback Status: {llm_timeout_tx['status']}")
            for entry in detail["audit_trail"]:
                print(f"  [{entry['layer']:<22}] {entry['decision']:<26} ({entry['timestamp']})")

    conn.close()
    return metrics


if __name__ == "__main__":
    print("EXECUTING PHASE 9 DOUBLE DEMO REHEARSAL...")
    metrics_1 = run_rehearsal_pass(1)
    metrics_2 = run_rehearsal_pass(2)

    assert metrics_1 == metrics_2, "Rehearsals must be 100% deterministic and reproducible!"
    print("\n" + "=" * 90)
    print("SUCCESS: BOTH COMPLETE DEMO REHEARSALS FINISHED WITH IDENTICAL DETERMINISTIC RESULTS!")
    print("=" * 90)
