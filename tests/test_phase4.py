import pytest
import sqlite3
from datetime import datetime
from src.models import (
    ActionType,
    ExecutionStatusEnum,
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
)
from src.db import (
    init_db,
    insert_risk_event,
    get_execution,
    get_executions_for_risk,
)
from src.executor import execute_action, generate_execution_id


@pytest.fixture
def in_memory_db():
    """Provides an initialized in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestActionExecutor:
    @pytest.mark.parametrize(
        "action_type",
        [
            ActionType.SMART_RETRY,
            ActionType.DELAYED_RETRY,
            ActionType.PAYMENT_LINK,
            ActionType.REMINDER,
            ActionType.DISCOUNT_NUDGE,
            ActionType.ESCALATE,
        ],
    )
    def test_all_action_types_can_be_invoked_successfully(self, action_type):
        result = execute_action(
            risk_id="risk_exec_001",
            action_index=0,
            action_type=action_type,
            amount=5000.0,
            customer_id="cust_001",
            simulate_status=ExecutionStatusEnum.SUCCESS,
        )

        assert result.action_type == action_type
        assert result.status == ExecutionStatusEnum.SUCCESS
        assert result.execution_id.startswith(f"exec_{action_type.value}_")
        assert result.details["simulated"] is True
        assert isinstance(result.executed_at, datetime)

    @pytest.mark.parametrize(
        "action_type",
        [
            ActionType.SMART_RETRY,
            ActionType.DELAYED_RETRY,
            ActionType.PAYMENT_LINK,
            ActionType.REMINDER,
            ActionType.DISCOUNT_NUDGE,
            ActionType.ESCALATE,
        ],
    )
    def test_all_action_types_can_simulate_failure(self, action_type):
        result = execute_action(
            risk_id="risk_exec_fail",
            action_index=0,
            action_type=action_type,
            amount=5000.0,
            customer_id="cust_fail",
            simulate_status=ExecutionStatusEnum.FAILED,
        )

        assert result.action_type == action_type
        assert result.status == ExecutionStatusEnum.FAILED
        assert result.execution_id.startswith(f"exec_{action_type.value}_")

    def test_execution_ids_are_unique(self):
        ids = set()
        for _ in range(50):
            exec_id = generate_execution_id(ActionType.SMART_RETRY)
            assert exec_id not in ids
            ids.add(exec_id)
        assert len(ids) == 50

    def test_invalid_action_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid or unsupported action_type"):
            execute_action(
                risk_id="risk_bad_action",
                action_index=0,
                action_type="unsupported_action",  # type: ignore
                amount=1000.0,
                customer_id="cust_bad",
            )

    def test_execution_persisted_to_sqlite(self, in_memory_db):
        risk = RiskEvent(
            risk_id="risk_exec_db_001",
            event_id="pay_exec_db_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=12000.0,
            priority=Priority.HIGH,
            status=EventStatus.DETECTED,
        )
        insert_risk_event(in_memory_db, risk)

        result_1 = execute_action(
            risk_id="risk_exec_db_001",
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            amount=12000.0,
            customer_id="cust_db_001",
            simulate_status=ExecutionStatusEnum.FAILED,
            conn=in_memory_db,
        )

        result_2 = execute_action(
            risk_id="risk_exec_db_001",
            action_index=1,
            action_type=ActionType.PAYMENT_LINK,
            amount=12000.0,
            customer_id="cust_db_001",
            simulate_status=ExecutionStatusEnum.SUCCESS,
            conn=in_memory_db,
        )

        # Retrieve individual execution
        exec_1 = get_execution(in_memory_db, result_1.execution_id)
        assert exec_1 is not None
        assert exec_1.risk_id == "risk_exec_db_001"
        assert exec_1.action_index == 0
        assert exec_1.action_type == ActionType.SMART_RETRY
        assert exec_1.status == ExecutionStatusEnum.FAILED

        exec_2 = get_execution(in_memory_db, result_2.execution_id)
        assert exec_2 is not None
        assert exec_2.risk_id == "risk_exec_db_001"
        assert exec_2.action_index == 1
        assert exec_2.action_type == ActionType.PAYMENT_LINK
        assert exec_2.status == ExecutionStatusEnum.SUCCESS

        # Retrieve list of executions
        all_execs = get_executions_for_risk(in_memory_db, "risk_exec_db_001")
        assert len(all_execs) == 2


class TestPhase4DoneWhenCriterion:
    def test_phase4_done_when_criterion(self, in_memory_db):
        """
        Phase 4 "Done when" criterion:
        Each action type can be called and logged, success/fail simulated.
        """
        risk = RiskEvent(
            risk_id="risk_done_p4",
            event_id="pay_done_p4",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=7500.0,
            priority=Priority.MEDIUM,
            status=EventStatus.DETECTED,
        )
        insert_risk_event(in_memory_db, risk)

        action_types = [
            ActionType.SMART_RETRY,
            ActionType.PAYMENT_LINK,
            ActionType.DELAYED_RETRY,
            ActionType.REMINDER,
            ActionType.DISCOUNT_NUDGE,
            ActionType.ESCALATE,
        ]

        # Call and log each action type with alternating SUCCESS/FAILED simulation
        for idx, act in enumerate(action_types):
            sim_status = ExecutionStatusEnum.SUCCESS if idx % 2 == 0 else ExecutionStatusEnum.FAILED
            res = execute_action(
                risk_id="risk_done_p4",
                action_index=idx,
                action_type=act,
                amount=7500.0,
                customer_id="cust_p4",
                simulate_status=sim_status,
                conn=in_memory_db,
            )

            assert res.execution_id.startswith(f"exec_{act.value}_")
            assert res.status == sim_status

            # Verify in DB
            db_record = get_execution(in_memory_db, res.execution_id)
            assert db_record is not None
            assert db_record.risk_id == "risk_done_p4"
            assert db_record.action_index == idx
            assert db_record.action_type == act
            assert db_record.status == sim_status

        # Verify all 6 executions logged in DB for this risk
        records = get_executions_for_risk(in_memory_db, "risk_done_p4")
        assert len(records) == 6
