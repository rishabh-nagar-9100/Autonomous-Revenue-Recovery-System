import os
import json
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.models import (
    Receivable,
    ReceivableStatusEnum,
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
    RootCauseEnum,
    ActionType,
    ExecutionStatusEnum,
    OutcomeResultEnum,
)
from src.db import (
    init_db,
    insert_risk_event,
    get_risk_event,
    get_outcomes_for_risk,
    get_escalation,
    get_receivable,
    list_receivables,
    get_executions_for_risk,
)
from src.decision_engine import next_action, PLAYBOOK
from src.receivables import evaluate_receivable_root_cause, process_b2b_receivable


@pytest.fixture
def memory_db():
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestPhase12B2BReceivables:
    def test_overdue_detection_and_root_cause(self):
        now = datetime.utcnow()
        due_past = now - timedelta(days=15)
        p2p_past = now - timedelta(days=2)
        p2p_future = now + timedelta(days=5)

        # Case 1: Missed promise date
        rec1 = Receivable(
            receivable_id="rec_p2p_1",
            customer_id="cust_b2b_1",
            invoice_id="inv_101",
            amount_due=15000.0,
            due_date=due_past,
            days_overdue=15,
            promise_to_pay_date=p2p_past,
        )
        assert evaluate_receivable_root_cause(rec1, now=now) == RootCauseEnum.PROMISE_TO_PAY_MISSED

        # Case 2: Promise date in future (not missed yet) -> standard overdue
        rec2 = Receivable(
            receivable_id="rec_p2p_2",
            customer_id="cust_b2b_2",
            invoice_id="inv_102",
            amount_due=12000.0,
            due_date=due_past,
            days_overdue=15,
            promise_to_pay_date=p2p_future,
        )
        assert evaluate_receivable_root_cause(rec2, now=now) == RootCauseEnum.RECEIVABLE_OVERDUE

        # Case 3: Chronic non-payer (>90 days overdue)
        rec3 = Receivable(
            receivable_id="rec_chronic_1",
            customer_id="cust_b2b_3",
            invoice_id="inv_103",
            amount_due=50000.0,
            due_date=now - timedelta(days=95),
            days_overdue=95,
        )
        assert evaluate_receivable_root_cause(rec3, now=now) == RootCauseEnum.CHRONIC_NON_PAYER

        # Case 4: Standard receivable overdue
        rec4 = Receivable(
            receivable_id="rec_std_1",
            customer_id="cust_b2b_4",
            invoice_id="inv_104",
            amount_due=8000.0,
            due_date=due_past,
            days_overdue=15,
        )
        assert evaluate_receivable_root_cause(rec4, now=now) == RootCauseEnum.RECEIVABLE_OVERDUE

    def test_b2b_playbook_definitions(self):
        # receivable_overdue -> [reminder, payment_link, escalate_to_crm]
        assert next_action(RootCauseEnum.RECEIVABLE_OVERDUE, 0) == ActionType.REMINDER
        assert next_action(RootCauseEnum.RECEIVABLE_OVERDUE, 1) == ActionType.PAYMENT_LINK
        assert next_action(RootCauseEnum.RECEIVABLE_OVERDUE, 2) == ActionType.ESCALATE_TO_CRM
        assert next_action(RootCauseEnum.RECEIVABLE_OVERDUE, 3) is None

        # promise_to_pay_missed -> [reminder, payment_link, escalate_to_collections]
        assert next_action(RootCauseEnum.PROMISE_TO_PAY_MISSED, 0) == ActionType.REMINDER
        assert next_action(RootCauseEnum.PROMISE_TO_PAY_MISSED, 1) == ActionType.PAYMENT_LINK
        assert next_action(RootCauseEnum.PROMISE_TO_PAY_MISSED, 2) == ActionType.ESCALATE_TO_COLLECTIONS
        assert next_action(RootCauseEnum.PROMISE_TO_PAY_MISSED, 3) is None

    def test_existing_payment_recent_overdue_playbook_unchanged(self):
        """CRITICAL REGRESSION TEST: recent_overdue MUST remain [reminder, payment_link] and index 2 MUST return None."""
        assert next_action(RootCauseEnum.RECENT_OVERDUE, 0) == ActionType.REMINDER
        assert next_action(RootCauseEnum.RECENT_OVERDUE, 1) == ActionType.PAYMENT_LINK
        assert next_action(RootCauseEnum.RECENT_OVERDUE, 2) is None
        assert PLAYBOOK["recent_overdue"] == ["reminder", "payment_link"]

    def test_b2b_enabled_feature_flag_gating(self, memory_db):
        receivable_data = {
            "receivable_id": "rec_gate_1",
            "customer_id": "cust_gate_1",
            "invoice_id": "inv_gate_1",
            "amount_due": 10000.0,
            "due_date": (datetime.utcnow() - timedelta(days=10)).isoformat(),
        }

        # Feature disabled -> raises PermissionError
        with patch.dict(os.environ, {"B2B_ENABLED": "false"}):
            with pytest.raises(PermissionError, match="B2B Receivables Recovery is disabled"):
                process_b2b_receivable(memory_db, receivable_data)

            assert get_receivable(memory_db, "rec_gate_1") is None
            assert len(list_receivables(memory_db)) == 0


class TestPhase12RuntimeTraces:
    def test_trace_a_invoice_overdue_successful_recovery(self, memory_db):
        """
        TRACE A: invoice overdue -> receivable_overdue -> reminder -> payment_link -> SUCCESS -> recovered receivable
        """
        due = (datetime.utcnow() - timedelta(days=20)).isoformat()
        rec_data = {
            "receivable_id": "rec_trace_a",
            "customer_id": "cust_trace_a",
            "invoice_id": "inv_trace_a",
            "amount_due": 25000.0,
            "due_date": due,
        }

        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            # Action 0 (reminder) fails, Action 1 (payment_link) succeeds
            res = process_b2b_receivable(
                memory_db,
                rec_data,
                simulated_action_outcomes={0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.SUCCESS},
            )

        assert res["status"] == "RECOVERED"
        assert res["root_cause"] == "receivable_overdue"
        assert res["amount_recovered"] == 25000.0

        # Verify receivable DB status updated to RECOVERED
        db_rec = get_receivable(memory_db, "rec_trace_a")
        assert db_rec is not None
        assert db_rec.status == ReceivableStatusEnum.RECOVERED

        # Verify executions recorded
        execs = get_executions_for_risk(memory_db, "risk_b2b_rec_trace_a")
        assert len(execs) == 2
        assert execs[0].action_type == ActionType.REMINDER
        assert execs[1].action_type == ActionType.PAYMENT_LINK
        assert execs[1].status == ExecutionStatusEnum.SUCCESS

    def test_trace_b_promise_to_pay_missed_escalate_to_collections(self, memory_db):
        """
        TRACE B: promise_to_pay_missed -> reminder -> payment_link -> failure -> escalate_to_collections
        """
        now = datetime.utcnow()
        due = (now - timedelta(days=30)).isoformat()
        p2p_past = (now - timedelta(days=3)).isoformat()

        rec_data = {
            "receivable_id": "rec_trace_b",
            "customer_id": "cust_trace_b",
            "invoice_id": "inv_trace_b",
            "amount_due": 45000.0,
            "due_date": due,
            "promise_to_pay_date": p2p_past,
        }

        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            # Action 0 (reminder) fails, Action 1 (payment_link) fails -> Action 2 (escalate_to_collections) executes
            res = process_b2b_receivable(
                memory_db,
                rec_data,
                simulated_action_outcomes={
                    0: ExecutionStatusEnum.FAILED,
                    1: ExecutionStatusEnum.FAILED,
                    2: ExecutionStatusEnum.SUCCESS,
                },
            )

        assert res["root_cause"] == "promise_to_pay_missed"

        execs = get_executions_for_risk(memory_db, "risk_b2b_rec_trace_b")
        assert len(execs) == 3
        assert execs[0].action_type == ActionType.REMINDER
        assert execs[1].action_type == ActionType.PAYMENT_LINK
        assert execs[2].action_type == ActionType.ESCALATE_TO_COLLECTIONS

    def test_trace_c_payment_recent_overdue_no_third_action(self, memory_db):
        """
        TRACE C: payment recent_overdue -> reminder -> payment_link -> no third action (index 2 returns None)
        """
        risk_id = "risk_trace_c_payment"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_c_payment",
            risk_type=RiskType.RECENT_OVERDUE,
            amount=3500.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        from src.models import RootCause
        from src.db import insert_root_cause
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.RECENT_OVERDUE, confidence=1.0))

        # Both action 0 and action 1 fail -> playbook exhausted
        from src.outcome_tracker import start_recovery_workflow
        res = start_recovery_workflow(
            conn=memory_db,
            risk_id=risk_id,
            simulated_action_outcomes={0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.FAILED},
        )

        assert res.final_status == EventStatus.ESCALATED
        assert res.reason == "playbook_exhausted"

        # Verify exactly 2 actions executed (reminder, payment_link). Index 2 returned None!
        execs = get_executions_for_risk(memory_db, risk_id)
        assert len(execs) == 2
        assert execs[0].action_type == ActionType.REMINDER
        assert execs[1].action_type == ActionType.PAYMENT_LINK
        assert next_action(RootCauseEnum.RECENT_OVERDUE, 2) is None

    def test_trace_d_b2b_feature_disabled_no_db_side_effects(self, memory_db):
        """
        TRACE D: B2B feature disabled (B2B_ENABLED=false) -> endpoint rejected/no-op -> no DB side effects
        """
        rec_data = {
            "receivable_id": "rec_trace_d",
            "customer_id": "cust_trace_d",
            "invoice_id": "inv_trace_d",
            "amount_due": 18000.0,
            "due_date": (datetime.utcnow() - timedelta(days=12)).isoformat(),
        }

        with patch.dict(os.environ, {"B2B_ENABLED": "false"}):
            with pytest.raises(PermissionError):
                process_b2b_receivable(memory_db, rec_data)

        # VERIFY ZERO DB SIDE EFFECTS
        assert get_receivable(memory_db, "rec_trace_d") is None
        assert get_risk_event(memory_db, "risk_b2b_rec_trace_d") is None
        assert len(list_receivables(memory_db)) == 0
