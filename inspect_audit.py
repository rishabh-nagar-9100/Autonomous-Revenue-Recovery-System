import sqlite3
import json
from datetime import datetime
from src.db import init_db
from src.pipeline import process_payment_failed_event
from src.guardrails import GuardrailContext
from src.outcome_tracker import start_recovery_workflow
from src.audit import get_audit_trail
from src.models import ExecutionStatusEnum


def print_audit_trace(conn: sqlite3.Connection, risk_id: str, title: str):
    print("=" * 100)
    print(f"AUDIT TRAIL TRACE: {title} (risk_id: {risk_id})")
    print("=" * 100)
    trail = get_audit_trail(conn, risk_id)
    print(f"Total audit records: {len(trail)}\n")
    print(f"{'ID':<4} | {'LAYER':<22} | {'DECISION':<26} | {'TIMESTAMP':<26}")
    print("-" * 100)
    for entry in trail:
        print(f"{entry.id:<4} | {entry.layer:<22} | {entry.decision:<26} | {entry.timestamp.isoformat():<26}")
        print(f"       -> Input : {entry.input_json}")
        print(f"       -> Output: {entry.output_json}")
        print()


def run_traces():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # 1. Recovered Transaction
    webhook_rec = {
        "entity": "event",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_audit_rec_100",
                    "amount": 2500000,  # 25,000 INR
                    "currency": "INR",
                    "customer_id": "cust_corp_rec",
                    "error_code": "GATEWAY_ERROR",
                    "error_reason": "payment_timed_out",
                    "error_description": "Bank network timeout during checkout.",
                }
            }
        },
    }
    norm_1, risk_1, rc_1 = process_payment_failed_event(webhook_rec, conn)
    daytime_ctx = GuardrailContext(current_time=datetime(2026, 8, 27, 14, 0, 0))
    start_recovery_workflow(
        conn=conn,
        risk_id=risk_1.risk_id,
        context=daytime_ctx,
        simulated_action_outcomes={
            0: ExecutionStatusEnum.FAILED,
            1: ExecutionStatusEnum.SUCCESS,
        },
        customer_id="cust_corp_rec",
    )
    print_audit_trace(conn, risk_1.risk_id, "Recovered Transaction (bank_timeout -> smart_retry FAIL -> payment_link SUCCESS)")

    # 2. Blocked & Escalated Transaction
    webhook_block = {
        "entity": "event",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_audit_block_200",
                    "amount": 1000000,
                    "currency": "INR",
                    "customer_id": "cust_retail_block",
                    "error_code": "GATEWAY_ERROR",
                    "error_reason": "payment_timed_out",
                    "error_description": "Timeout",
                }
            }
        },
    }
    norm_2, risk_2, rc_2 = process_payment_failed_event(webhook_block, conn)
    night_ctx = GuardrailContext(current_time=datetime(2026, 8, 27, 23, 15, 0))
    start_recovery_workflow(
        conn=conn,
        risk_id=risk_2.risk_id,
        context=night_ctx,
        simulated_action_outcomes={
            0: ExecutionStatusEnum.FAILED,
            1: ExecutionStatusEnum.SUCCESS,
        },
        customer_id="cust_retail_block",
    )
    print_audit_trace(conn, risk_2.risk_id, "Blocked & Escalated Transaction (DND night time 23:15 -> Guardrail BLOCK -> Escalation)")

    conn.close()


if __name__ == "__main__":
    run_traces()
