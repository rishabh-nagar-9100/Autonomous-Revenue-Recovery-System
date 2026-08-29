import pytest
import sqlite3
from datetime import datetime
from src.models import (
    RootCauseEnum,
    ActionType,
    Intervention,
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
)
from src.db import (
    init_db,
    insert_risk_event,
    insert_intervention,
    get_intervention,
    get_interventions_for_risk,
)
from src.decision_engine import PLAYBOOK, next_action, record_intervention


@pytest.fixture
def in_memory_db():
    """Provides an initialized in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestDecisionEnginePlaybook:
    def test_playbook_structure_matches_architecture_spec(self):
        expected_playbook = {
            "bank_timeout": ["smart_retry", "payment_link"],
            "nsf": ["delayed_retry", "payment_link"],
            "expired_card": ["payment_link", "reminder"],
            "cart_abandonment": ["discount_nudge", "reminder"],
            "recent_overdue": ["reminder", "payment_link"],
            "chronic_non_payer": [],
        }
        for k, v in expected_playbook.items():
            assert PLAYBOOK.get(k) == v

    @pytest.mark.parametrize(
        "root_cause,expected_actions",
        [
            ("bank_timeout", [ActionType.SMART_RETRY, ActionType.PAYMENT_LINK]),
            ("nsf", [ActionType.DELAYED_RETRY, ActionType.PAYMENT_LINK]),
            ("expired_card", [ActionType.PAYMENT_LINK, ActionType.REMINDER]),
            ("cart_abandonment", [ActionType.DISCOUNT_NUDGE, ActionType.REMINDER]),
            ("recent_overdue", [ActionType.REMINDER, ActionType.PAYMENT_LINK]),
        ],
    )
    def test_all_playbook_sequences(self, root_cause, expected_actions):
        # Index 0 returns first action
        assert next_action(root_cause, 0) == expected_actions[0]
        # Index 1 returns second action
        assert next_action(root_cause, 1) == expected_actions[1]
        # Index 2 (end of list) returns None
        assert next_action(root_cause, 2) is None
        # Subsequent indices return None
        assert next_action(root_cause, 3) is None

    def test_chronic_non_payer_returns_none_immediately(self):
        assert next_action(RootCauseEnum.CHRONIC_NON_PAYER, 0) is None
        assert next_action("chronic_non_payer", 0) is None

    def test_root_cause_enum_and_string_equivalence(self):
        assert next_action(RootCauseEnum.BANK_TIMEOUT, 0) == ActionType.SMART_RETRY
        assert next_action("bank_timeout", 0) == ActionType.SMART_RETRY
        assert next_action(RootCauseEnum.NSF, 0) == ActionType.DELAYED_RETRY
        assert next_action("nsf", 0) == ActionType.DELAYED_RETRY

    def test_invalid_and_unknown_root_causes(self):
        assert next_action("unknown", 0) is None
        assert next_action(RootCauseEnum.UNKNOWN, 0) is None
        assert next_action("invalid_category", 0) is None
        assert next_action("", 0) is None

    def test_negative_index_returns_none(self):
        assert next_action(RootCauseEnum.BANK_TIMEOUT, -1) is None
        assert next_action("bank_timeout", -5) is None


class TestInterventionsDatabase:
    def test_insert_and_retrieve_intervention(self, in_memory_db):
        # Setup parent risk_event
        risk = RiskEvent(
            risk_id="risk_p2_001",
            event_id="pay_p2_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.DETECTED,
            created_at=datetime(2026, 8, 27, 11, 0, 0),
        )
        insert_risk_event(in_memory_db, risk)

        intervention = Intervention(
            risk_id="risk_p2_001",
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            draft_message=None,
            created_at=datetime(2026, 8, 27, 11, 1, 0),
        )
        insert_intervention(in_memory_db, intervention)

        retrieved = get_intervention(in_memory_db, "risk_p2_001", 0)
        assert retrieved is not None
        assert retrieved.risk_id == "risk_p2_001"
        assert retrieved.action_index == 0
        assert retrieved.action_type == ActionType.SMART_RETRY
        assert retrieved.draft_message is None
        assert retrieved.created_at == datetime(2026, 8, 27, 11, 1, 0)

    def test_record_intervention_helper(self, in_memory_db):
        risk = RiskEvent(
            risk_id="risk_p2_002",
            event_id="pay_p2_002",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=15000.0,
            priority=Priority.HIGH,
            status=EventStatus.DETECTED,
        )
        insert_risk_event(in_memory_db, risk)

        record_intervention(
            conn=in_memory_db,
            risk_id="risk_p2_002",
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,
            draft_message="Payment link generated for high priority invoice.",
        )

        record_intervention(
            conn=in_memory_db,
            risk_id="risk_p2_002",
            action_index=1,
            action_type=ActionType.REMINDER,
            draft_message="Reminder sent to customer.",
        )

        interventions = get_interventions_for_risk(in_memory_db, "risk_p2_002")
        assert len(interventions) == 2
        assert interventions[0].action_index == 0
        assert interventions[0].action_type == ActionType.PAYMENT_LINK
        assert interventions[1].action_index == 1
        assert interventions[1].action_type == ActionType.REMINDER


class TestPhase2DoneWhenCriterion:
    def test_phase2_done_when_criterion(self):
        """
        Phase 2 "Done when" criterion:
        Given a root_cause + failed action_index, correct next action is returned,
        and None is returned correctly at end of list.
        """
        root_cause = "bank_timeout"

        # Action 0 (initial action)
        action_0 = next_action(root_cause, 0)
        assert action_0 == ActionType.SMART_RETRY

        # Action 0 failed -> retrieve next action (index 1)
        action_1 = next_action(root_cause, 1)
        assert action_1 == ActionType.PAYMENT_LINK

        # Action 1 failed -> retrieve next action (index 2, end of playbook)
        action_2 = next_action(root_cause, 2)
        assert action_2 is None

        # Chronic non payer: immediate end of playbook (None)
        assert next_action("chronic_non_payer", 0) is None
