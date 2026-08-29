import sqlite3
import json
from datetime import datetime
from src.models import (
    RiskEvent,
    RootCause,
    RiskType,
    Priority,
    EventStatus,
    RootCauseEnum,
    ExecutionStatusEnum,
)
from src.db import (
    init_db,
    insert_risk_event,
    insert_root_cause,
)
from src.guardrails import GuardrailContext
from src.outcome_tracker import start_recovery_workflow


def dump_table(conn: sqlite3.Connection, table_name: str, risk_id: str):
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name} WHERE risk_id = ?", (risk_id,))
    rows = cursor.fetchall()
    if not rows:
        print(f"  [{table_name}]: (0 rows)")
        return
    print(f"  [{table_name}]: ({len(rows)} rows)")
    for r in rows:
        row_dict = dict(r)
        print("   ", json.dumps(row_dict, default=str))


def run_scenario_1(conn: sqlite3.Connection):
    risk_id = "risk_scen_1_trace"
    print("=" * 80)
    print("SCENARIO 1: bank_timeout -> smart_retry FAILED -> payment_link SUCCESS -> ₹ recovered")
    print("=" * 80)

    # Ingestion & Detection setup
    risk = RiskEvent(
        risk_id=risk_id,
        event_id="pay_scen_1_001",
        risk_type=RiskType.PAYMENT_FAILED,
        amount=15000.0,
        priority=Priority.HIGH,
        status=EventStatus.DETECTED,
    )
    insert_risk_event(conn, risk)
    insert_root_cause(conn, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0, source="rule"))

    # Execute Recovery Workflow (2:00 PM daytime context)
    daytime_ctx = GuardrailContext(current_time=datetime(2026, 8, 27, 14, 0, 0))
    result = start_recovery_workflow(
        conn=conn,
        risk_id=risk_id,
        context=daytime_ctx,
        simulated_action_outcomes={
            0: ExecutionStatusEnum.FAILED,   # smart_retry fails
            1: ExecutionStatusEnum.SUCCESS,  # payment_link succeeds
        },
        customer_id="cust_corp_01",
    )

    print(f"Final Workflow Result: Status={result.final_status.value}, Amount Recovered=₹{result.amount_recovered}, Reason={result.reason}")
    print("\nDatabase State:")
    for tbl in ["risk_events", "root_causes", "interventions", "guardrail_checks", "executions", "outcomes", "escalations"]:
        dump_table(conn, tbl, risk_id)


def run_scenario_2(conn: sqlite3.Connection):
    risk_id = "risk_scen_2_trace"
    print("\n" + "=" * 80)
    print("SCENARIO 2: bank_timeout -> smart_retry FAILED -> payment_link FAILED -> playbook_exhausted -> escalation")
    print("=" * 80)

    risk = RiskEvent(
        risk_id=risk_id,
        event_id="pay_scen_2_001",
        risk_type=RiskType.PAYMENT_FAILED,
        amount=8000.0,
        priority=Priority.MEDIUM,
        status=EventStatus.DETECTED,
    )
    insert_risk_event(conn, risk)
    insert_root_cause(conn, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0, source="rule"))

    daytime_ctx = GuardrailContext(current_time=datetime(2026, 8, 27, 14, 0, 0))
    result = start_recovery_workflow(
        conn=conn,
        risk_id=risk_id,
        context=daytime_ctx,
        simulated_action_outcomes={
            0: ExecutionStatusEnum.FAILED,   # smart_retry fails
            1: ExecutionStatusEnum.FAILED,   # payment_link fails
        },
        customer_id="cust_retail_02",
    )

    print(f"Final Workflow Result: Status={result.final_status.value}, Amount Recovered=₹{result.amount_recovered}, Reason={result.reason}")
    print("\nDatabase State:")
    for tbl in ["risk_events", "root_causes", "interventions", "guardrail_checks", "executions", "outcomes", "escalations"]:
        dump_table(conn, tbl, risk_id)


def run_scenario_3(conn: sqlite3.Connection):
    risk_id = "risk_scen_3_trace"
    print("\n" + "=" * 80)
    print("SCENARIO 3: smart_retry FAILED -> next action payment_link -> guardrail BLOCK (dnd_hours) -> escalation")
    print("=" * 80)

    risk = RiskEvent(
        risk_id=risk_id,
        event_id="pay_scen_3_001",
        risk_type=RiskType.PAYMENT_FAILED,
        amount=10000.0,
        priority=Priority.HIGH,
        status=EventStatus.DETECTED,
    )
    insert_risk_event(conn, risk)
    insert_root_cause(conn, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0, source="rule"))

    # Night context (11:00 PM)
    night_ctx = GuardrailContext(current_time=datetime(2026, 8, 27, 23, 0, 0))
    result = start_recovery_workflow(
        conn=conn,
        risk_id=risk_id,
        context=night_ctx,
        simulated_action_outcomes={
            0: ExecutionStatusEnum.FAILED,   # smart_retry allowed during DND, but fails
            1: ExecutionStatusEnum.SUCCESS,  # payment_link is customer-facing, will be blocked by DND
        },
        customer_id="cust_retail_03",
    )

    print(f"Final Workflow Result: Status={result.final_status.value}, Amount Recovered=₹{result.amount_recovered}, Reason={result.reason}")
    print("\nDatabase State:")
    for tbl in ["risk_events", "root_causes", "interventions", "guardrail_checks", "executions", "outcomes", "escalations"]:
        dump_table(conn, tbl, risk_id)


if __name__ == "__main__":
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    run_scenario_1(conn)
    run_scenario_2(conn)
    run_scenario_3(conn)
    conn.close()
