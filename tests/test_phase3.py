import pytest
import sqlite3
from datetime import datetime, timedelta
from src.models import (
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
    ActionType,
    GuardrailResultEnum,
)
from src.db import (
    init_db,
    insert_risk_event,
    get_guardrail_check,
    get_guardrail_checks_for_risk,
)
from src.guardrails import (
    GuardrailContext,
    evaluate_guardrails,
    evaluate_and_record_guardrails,
)


@pytest.fixture
def in_memory_db():
    """Provides an initialized in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestRetryCapGuardrail:
    def test_attempt_number_5_blocked_with_retry_cap_exceeded(self):
        ctx = GuardrailContext(attempt_number=5)
        check = evaluate_guardrails(
            risk_id="risk_rc_001",
            amount=5000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "retry_cap_exceeded"

    def test_attempt_number_6_blocked_with_retry_cap_exceeded(self):
        ctx = GuardrailContext(attempt_number=6)
        check = evaluate_guardrails(
            risk_id="risk_rc_002",
            amount=5000.0,
            action_index=1,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "retry_cap_exceeded"

    def test_attempt_number_under_or_equal_to_4_passes(self):
        for attempt in [1, 2, 3, 4]:
            ctx = GuardrailContext(
                attempt_number=attempt,
                current_time=datetime(2026, 8, 27, 12, 0, 0),  # Allowed hours
            )
            check = evaluate_guardrails(
                risk_id=f"risk_rc_pass_{attempt}",
                amount=5000.0,
                action_index=0,
                action_type=ActionType.SMART_RETRY,
                context=ctx,
            )
            assert check.result == GuardrailResultEnum.PASS
            assert check.reason is None


class TestMandateNoticeGuardrail:
    def test_mandate_without_notice_blocks_retry(self):
        ctx = GuardrailContext(
            is_mandate=True,
            mandate_notice_served=False,
            current_time=datetime(2026, 8, 27, 12, 0, 0),
        )
        check = evaluate_guardrails(
            risk_id="risk_mandate_001",
            amount=2000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "mandate_notice_required"

    def test_mandate_with_notice_served_passes(self):
        ctx = GuardrailContext(
            is_mandate=True,
            mandate_notice_served=True,
            current_time=datetime(2026, 8, 27, 12, 0, 0),
        )
        check = evaluate_guardrails(
            risk_id="risk_mandate_002",
            amount=2000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None


class TestCooldownGuardrail:
    def test_cooldown_active_blocks_retry_within_4_hours(self):
        now = datetime(2026, 8, 27, 14, 0, 0)
        last_retry = now - timedelta(hours=2)
        ctx = GuardrailContext(
            last_retry_at=last_retry,
            current_time=now,
        )
        check = evaluate_guardrails(
            risk_id="risk_cool_001",
            amount=1500.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "cooldown_active"

    def test_cooldown_elapsed_allows_retry(self):
        now = datetime(2026, 8, 27, 14, 0, 0)
        last_retry = now - timedelta(hours=4, minutes=5)
        ctx = GuardrailContext(
            last_retry_at=last_retry,
            current_time=now,
        )
        check = evaluate_guardrails(
            risk_id="risk_cool_002",
            amount=1500.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None


class TestDndHoursGuardrail:
    def test_customer_facing_action_during_night_dnd_is_blocked(self):
        night_time = datetime(2026, 8, 27, 22, 30, 0)  # 10:30 PM
        ctx = GuardrailContext(current_time=night_time)
        check = evaluate_guardrails(
            risk_id="risk_dnd_001",
            amount=2000.0,
            action_index=1,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "dnd_hours"

    def test_customer_facing_action_early_morning_dnd_is_blocked(self):
        early_morning = datetime(2026, 8, 27, 7, 0, 0)  # 7:00 AM
        ctx = GuardrailContext(current_time=early_morning)
        check = evaluate_guardrails(
            risk_id="risk_dnd_002",
            amount=2000.0,
            action_index=1,
            action_type=ActionType.REMINDER,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "dnd_hours"

    def test_customer_facing_action_inside_allowed_hours_passes(self):
        day_time = datetime(2026, 8, 27, 14, 30, 0)  # 2:30 PM
        ctx = GuardrailContext(current_time=day_time)
        check = evaluate_guardrails(
            risk_id="risk_dnd_003",
            amount=2000.0,
            action_index=1,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None

    def test_backend_smart_retry_allowed_during_dnd_hours(self):
        night_time = datetime(2026, 8, 27, 23, 0, 0)  # 11:00 PM
        ctx = GuardrailContext(current_time=night_time)
        check = evaluate_guardrails(
            risk_id="risk_dnd_004",
            amount=2000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None


class TestCustomerOptedOutGuardrail:
    def test_customer_opted_out_blocks_customer_facing_action(self):
        ctx = GuardrailContext(
            customer_opted_out=True,
            current_time=datetime(2026, 8, 27, 12, 0, 0),
        )
        check = evaluate_guardrails(
            risk_id="risk_optout_001",
            amount=3000.0,
            action_index=1,
            action_type=ActionType.REMINDER,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "customer_opted_out"

    def test_customer_opted_out_allows_backend_retry(self):
        ctx = GuardrailContext(
            customer_opted_out=True,
            current_time=datetime(2026, 8, 27, 12, 0, 0),
        )
        check = evaluate_guardrails(
            risk_id="risk_optout_002",
            amount=3000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None


class TestAmountRequiresHumanApprovalGuardrail:
    def test_amount_above_threshold_is_blocked(self):
        ctx = GuardrailContext(
            current_time=datetime(2026, 8, 27, 12, 0, 0),
            human_approval_threshold=50000.0,
        )
        check = evaluate_guardrails(
            risk_id="risk_amt_001",
            amount=75000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "amount_requires_human_approval"

    def test_amount_below_threshold_passes(self):
        ctx = GuardrailContext(
            current_time=datetime(2026, 8, 27, 12, 0, 0),
            human_approval_threshold=50000.0,
        )
        check = evaluate_guardrails(
            risk_id="risk_amt_002",
            amount=49999.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None


class TestGuardrailPriorityOrder:
    def test_retry_cap_has_higher_priority_than_dnd_and_amount(self):
        # Multiple violations: attempt_number=5 (rule 1), dnd night (rule 4), amount 100k (rule 6)
        ctx = GuardrailContext(
            attempt_number=5,
            current_time=datetime(2026, 8, 27, 23, 0, 0),
        )
        check = evaluate_guardrails(
            risk_id="risk_prio_001",
            amount=100000.0,
            action_index=1,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx,
        )
        # Priority rule 1 wins
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "retry_cap_exceeded"

    def test_mandate_notice_has_higher_priority_than_cooldown(self):
        # Violations: mandate notice missing (rule 2) + cooldown active (rule 3)
        now = datetime(2026, 8, 27, 12, 0, 0)
        ctx = GuardrailContext(
            is_mandate=True,
            mandate_notice_served=False,
            last_retry_at=now - timedelta(hours=1),
            current_time=now,
        )
        check = evaluate_guardrails(
            risk_id="risk_prio_002",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "mandate_notice_required"


class TestGuardrailDatabasePersistenceAndDoneCriteria:
    def test_guardrail_check_persisted_to_sqlite(self, in_memory_db):
        risk = RiskEvent(
            risk_id="risk_gdb_001",
            event_id="pay_gdb_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=80000.0,
            priority=Priority.HIGH,
            status=EventStatus.DETECTED,
        )
        insert_risk_event(in_memory_db, risk)

        ctx = GuardrailContext(
            current_time=datetime(2026, 8, 27, 11, 0, 0),
            human_approval_threshold=50000.0,
        )

        check = evaluate_and_record_guardrails(
            conn=in_memory_db,
            risk_id="risk_gdb_001",
            amount=80000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )

        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "amount_requires_human_approval"

        # Verify from SQLite
        retrieved = get_guardrail_check(in_memory_db, "risk_gdb_001", 0)
        assert retrieved is not None
        assert retrieved.risk_id == "risk_gdb_001"
        assert retrieved.action_index == 0
        assert retrieved.result == GuardrailResultEnum.BLOCK
        assert retrieved.reason == "amount_requires_human_approval"
        assert retrieved.checked_at == datetime(2026, 8, 27, 11, 0, 0)

    def test_phase3_done_when_criterion(self, in_memory_db):
        """
        Phase 3 "Done when" criterion:
        A synthetic case with attempt_number=5 is correctly BLOCKED with reason.
        """
        risk = RiskEvent(
            risk_id="risk_done_p3_001",
            event_id="pay_done_p3_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.DETECTED,
        )
        insert_risk_event(in_memory_db, risk)

        ctx = GuardrailContext(attempt_number=5)

        check = evaluate_and_record_guardrails(
            conn=in_memory_db,
            risk_id="risk_done_p3_001",
            amount=5000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )

        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "retry_cap_exceeded"

        # Verify persisted check
        checks = get_guardrail_checks_for_risk(in_memory_db, "risk_done_p3_001")
        assert len(checks) == 1
        assert checks[0].result == GuardrailResultEnum.BLOCK
        assert checks[0].reason == "retry_cap_exceeded"
