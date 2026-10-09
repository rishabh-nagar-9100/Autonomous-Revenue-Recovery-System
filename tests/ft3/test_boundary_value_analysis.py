"""
Boundary Value Analysis (BVA) Test Suite
Software Testing FT3 - Autonomous AI Revenue Recovery System

This module applies Boundary Value Analysis to the critical business thresholds
and safety conditions identified in the production system.
Each test exercises:
  1. Immediately below the boundary (Boundary - Delta)
  2. Exactly at the boundary (Boundary)
  3. Immediately above the boundary (Boundary + Delta)
"""

import os
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.models import (
    NormalizedEvent,
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
    RootCause,
    RootCauseEnum,
    ActionType,
    GuardrailResultEnum,
    Receivable,
)
from src.db import init_db, insert_risk_event, insert_root_cause
from src.risk_detector import detect_revenue_risk
from src.guardrails import evaluate_guardrails, GuardrailContext
from src.reconciliation import reconcile_payment_status
from src.receivables import evaluate_receivable_root_cause
from src.info_gathering import check_recovery_eligibility
from src.voice import check_voice_eligibility


@pytest.fixture
def memory_db():
    """In-memory SQLite database initialized with fresh schema."""
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


# ==============================================================================
# 1. REVENUE RISK DETECTOR BVA TESTS
# Implementation: src/risk_detector.py
# Thresholds:
#   - 2500.0: < 2500.0 -> LOW, >= 2500.0 -> MEDIUM
#   - 10000.0: < 10000.0 -> MEDIUM, >= 10000.0 -> HIGH
# ==============================================================================

class TestRiskDetectorAmountBVA:
    """BVA on transaction amount thresholds in detect_revenue_risk()."""

    @pytest.mark.parametrize(
        "amount,expected_priority",
        [
            (2499.99, Priority.LOW),      # Immediately below boundary
            (2500.00, Priority.MEDIUM),   # Exactly at boundary (>= 2500.0)
            (2500.01, Priority.MEDIUM),   # Immediately above boundary
        ],
        ids=["below_2500", "exact_2500", "above_2500"],
    )
    def test_risk_detector_amount_bva_2500(self, amount, expected_priority):
        """BVA-RD-01: Boundary test around ₹2,500.00 amount threshold."""
        event = NormalizedEvent(
            event_id=f"pay_bva_2500_{amount}",
            event_type="payment_failed",
            amount=amount,
            customer_id="cust_bva_1",
            metadata={"is_vip": False, "customer_tier": "standard"},
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == expected_priority

    @pytest.mark.parametrize(
        "amount,expected_priority",
        [
            (9999.99, Priority.MEDIUM),   # Immediately below boundary
            (10000.00, Priority.HIGH),    # Exactly at boundary (>= 10000.0)
            (10000.01, Priority.HIGH),    # Immediately above boundary
        ],
        ids=["below_10000", "exact_10000", "above_10000"],
    )
    def test_risk_detector_amount_bva_10000(self, amount, expected_priority):
        """BVA-RD-02: Boundary test around ₹10,000.00 amount threshold."""
        event = NormalizedEvent(
            event_id=f"pay_bva_10000_{amount}",
            event_type="payment_failed",
            amount=amount,
            customer_id="cust_bva_2",
            metadata={"is_vip": False, "customer_tier": "standard"},
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == expected_priority


# ==============================================================================
# 2. SAFETY GUARDRAILS BVA TESTS
# Implementation: src/guardrails.py
# Thresholds:
#   - MAX_RETRY_ATTEMPTS = 4: attempt_number > 4 -> BLOCK
#   - COOLDOWN_SECONDS = 14400: elapsed < 14400 -> BLOCK
#   - DND_START_HOUR = 9, DND_END_HOUR = 20: hour < 9 or hour >= 20 -> BLOCK
#   - DEFAULT_HUMAN_APPROVAL_AMOUNT_THRESHOLD = 50000.0: amount > 50000.0 -> BLOCK
# ==============================================================================

class TestGuardrailsBVA:
    """BVA on safety and compliance guardrails."""

    @pytest.mark.parametrize(
        "attempt_number,expected_result,expected_reason",
        [
            (3, GuardrailResultEnum.PASS, None),
            (4, GuardrailResultEnum.PASS, None),                      # Exactly at boundary (<= 4 passes)
            (5, GuardrailResultEnum.BLOCK, "retry_cap_exceeded"),      # Immediately above boundary (> 4 blocks)
        ],
        ids=["attempt_3_below", "attempt_4_boundary", "attempt_5_above"],
    )
    def test_guardrail_retry_count_bva_4(self, attempt_number, expected_result, expected_reason):
        """BVA-GR-01: Boundary test around MAX_RETRY_ATTEMPTS = 4."""
        ctx = GuardrailContext(
            attempt_number=attempt_number,
            current_time=datetime(2026, 8, 27, 14, 0, 0),  # Allowed daytime hours
        )
        check = evaluate_guardrails(
            risk_id="risk_bva_retry",
            amount=5000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == expected_result
        assert check.reason == expected_reason

    @pytest.mark.parametrize(
        "elapsed_seconds,expected_result,expected_reason",
        [
            (14399, GuardrailResultEnum.BLOCK, "cooldown_active"),    # Immediately below boundary (< 14400 blocks)
            (14400, GuardrailResultEnum.PASS, None),                  # Exactly at boundary (not < 14400 passes)
            (14401, GuardrailResultEnum.PASS, None),                  # Immediately above boundary passes
        ],
        ids=["elapsed_14399_below", "elapsed_14400_boundary", "elapsed_14401_above"],
    )
    def test_guardrail_cooldown_bva_14400(self, elapsed_seconds, expected_result, expected_reason):
        """BVA-GR-02: Boundary test around COOLDOWN_SECONDS = 14,400s (4 hours)."""
        now = datetime(2026, 8, 27, 15, 0, 0)
        last_retry = now - timedelta(seconds=elapsed_seconds)
        ctx = GuardrailContext(
            last_retry_at=last_retry,
            current_time=now,
        )
        check = evaluate_guardrails(
            risk_id="risk_bva_cooldown",
            amount=5000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == expected_result
        assert check.reason == expected_reason

    @pytest.mark.parametrize(
        "test_time,expected_result,expected_reason",
        [
            (datetime(2026, 8, 27, 8, 59, 59), GuardrailResultEnum.BLOCK, "dnd_hours"),  # Hour 8 < 9 -> BLOCK
            (datetime(2026, 8, 27, 9, 0, 0), GuardrailResultEnum.PASS, None),            # Hour 9 == 9 -> PASS
            (datetime(2026, 8, 27, 9, 1, 0), GuardrailResultEnum.PASS, None),            # Hour 9 == 9 -> PASS
        ],
        ids=["morning_0859_below", "morning_0900_boundary", "morning_0901_above"],
    )
    def test_guardrail_dnd_morning_bva_9am(self, test_time, expected_result, expected_reason):
        """BVA-GR-03A: Boundary test around Morning DND start hour (09:00 AM)."""
        ctx = GuardrailContext(current_time=test_time)
        check = evaluate_guardrails(
            risk_id="risk_bva_dnd_morning",
            amount=3000.0,
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,  # Customer-facing action
            context=ctx,
        )
        assert check.result == expected_result
        assert check.reason == expected_reason

    @pytest.mark.parametrize(
        "test_time,expected_result,expected_reason",
        [
            (datetime(2026, 8, 27, 19, 59, 59), GuardrailResultEnum.PASS, None),         # Hour 19 < 20 -> PASS
            (datetime(2026, 8, 27, 20, 0, 0), GuardrailResultEnum.BLOCK, "dnd_hours"),   # Hour 20 >= 20 -> BLOCK
            (datetime(2026, 8, 27, 20, 1, 0), GuardrailResultEnum.BLOCK, "dnd_hours"),   # Hour 20 >= 20 -> BLOCK
        ],
        ids=["evening_1959_below", "evening_2000_boundary", "evening_2001_above"],
    )
    def test_guardrail_dnd_evening_bva_8pm(self, test_time, expected_result, expected_reason):
        """BVA-GR-03B: Boundary test around Evening DND end hour (08:00 PM / 20:00)."""
        ctx = GuardrailContext(current_time=test_time)
        check = evaluate_guardrails(
            risk_id="risk_bva_dnd_evening",
            amount=3000.0,
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,  # Customer-facing action
            context=ctx,
        )
        assert check.result == expected_result
        assert check.reason == expected_reason

    @pytest.mark.parametrize(
        "amount,expected_result,expected_reason",
        [
            (49999.99, GuardrailResultEnum.PASS, None),                                  # Below threshold
            (50000.00, GuardrailResultEnum.PASS, None),                                  # Exactly at threshold (not > 50000.0)
            (50000.01, GuardrailResultEnum.BLOCK, "amount_requires_human_approval"),     # Above threshold (> 50000.0)
        ],
        ids=["amount_49999.99_below", "amount_50000.00_boundary", "amount_50000.01_above"],
    )
    def test_guardrail_human_approval_amount_bva_50000(self, amount, expected_result, expected_reason):
        """BVA-GR-04: Boundary test around Human Approval threshold (₹50,000.00)."""
        ctx = GuardrailContext(
            current_time=datetime(2026, 8, 27, 12, 0, 0),
            human_approval_threshold=50000.0,
        )
        check = evaluate_guardrails(
            risk_id="risk_bva_human_approval",
            amount=amount,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == expected_result
        assert check.reason == expected_reason


# ==============================================================================
# 3. RECONCILIATION ENGINE BVA TESTS
# Implementation: src/reconciliation.py
# Thresholds:
#   - MAX_RECONCILIATION_ATTEMPTS = 3: attempt_count >= 3 -> ESCALATED
#   - MAX_RECONCILIATION_HOURS = 24.0: elapsed_hours >= 24.0 -> ESCALATED
# ==============================================================================

class TestReconciliationBVA:
    """BVA on reconciliation attempts cap and elapsed time window."""

    @pytest.mark.parametrize(
        "attempts,expected_status",
        [
            (2, "pending_reconciliation"),   # Below boundary (< 3)
            (3, "escalated_timeout"),         # Exactly at boundary (>= 3)
            (4, "escalated_timeout"),         # Above boundary (> 3)
        ],
        ids=["attempts_2_below", "attempts_3_boundary", "attempts_4_above"],
    )
    def test_reconciliation_attempt_count_bva_3(self, memory_db, attempts, expected_status):
        """BVA-RC-01: Boundary test around MAX_RECONCILIATION_ATTEMPTS = 3."""
        risk_id = f"risk_recon_att_{attempts}"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id=f"evt_att_{attempts}",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1500.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id=risk_id,
            forced_status="UNKNOWN",  # Unresolved status to trigger timeout evaluation
            attempt_count=attempts,
            elapsed_hours=5.0,  # Below 24h
        )
        assert res["status"] == expected_status

    @pytest.mark.parametrize(
        "hours,expected_status",
        [
            (23.99, "pending_reconciliation"),  # Below boundary (< 24.0)
            (24.00, "escalated_timeout"),        # Exactly at boundary (>= 24.0)
            (24.01, "escalated_timeout"),        # Above boundary (> 24.0)
        ],
        ids=["hours_23.99_below", "hours_24.00_boundary", "hours_24.01_above"],
    )
    def test_reconciliation_elapsed_hours_bva_24(self, memory_db, hours, expected_status):
        """BVA-RC-02: Boundary test around MAX_RECONCILIATION_HOURS = 24.0."""
        risk_id = f"risk_recon_hrs_{hours}"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id=f"evt_hrs_{hours}",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1500.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id=risk_id,
            forced_status="UNKNOWN",  # Unresolved status to trigger timeout evaluation
            attempt_count=1,  # Below 3
            elapsed_hours=hours,
        )
        assert res["status"] == expected_status


# ==============================================================================
# 4. B2B RECEIVABLES BVA TESTS
# Implementation: src/receivables.py
# Threshold:
#   - days_overdue > 90: days_overdue > 90 -> CHRONIC_NON_PAYER
# ==============================================================================

class TestB2BReceivablesBVA:
    """BVA on B2B overdue invoice thresholds in evaluate_receivable_root_cause()."""

    @pytest.mark.parametrize(
        "days_overdue,expected_root_cause",
        [
            (89, RootCauseEnum.RECEIVABLE_OVERDUE),   # Below boundary
            (90, RootCauseEnum.RECEIVABLE_OVERDUE),   # Exactly at boundary (not > 90)
            (91, RootCauseEnum.CHRONIC_NON_PAYER),    # Above boundary (> 90)
        ],
        ids=["days_89_below", "days_90_boundary", "days_91_above"],
    )
    def test_b2b_days_overdue_bva_90(self, days_overdue, expected_root_cause):
        """BVA-B2B-01: Boundary test around 90 days overdue chronic default threshold."""
        now = datetime.utcnow()
        rec = Receivable(
            receivable_id=f"rec_bva_{days_overdue}",
            customer_id="cust_b2b_bva",
            invoice_id=f"inv_bva_{days_overdue}",
            amount_due=25000.0,
            due_date=now - timedelta(days=days_overdue),
            days_overdue=days_overdue,
            customer_tier="STANDARD",
            promise_to_pay_date=None,
        )
        assert evaluate_receivable_root_cause(rec, now=now) == expected_root_cause


# ==============================================================================
# 5. CUSTOMER INFORMATION GATHERING BVA TESTS
# Implementation: src/info_gathering.py
# Thresholds:
#   - INFO_RECOVERY_WINDOW_DAYS = 7: elapsed_days > 7 -> recovery_window_expired
#   - amount <= 0: amount <= 0 -> invalid_amount
# ==============================================================================

class TestCustomerInfoGatheringBVA:
    """BVA on customer information recovery window and transaction amount."""

    @pytest.mark.parametrize(
        "elapsed_days,expected_eligible,reason_substring",
        [
            (6.99, True, "PASS"),
            (7.00, True, "PASS"),                                   # Exactly at boundary (not > 7 days)
            (7.01, False, "recovery_window_expired"),               # Above boundary (> 7 days)
        ],
        ids=["days_6.99_below", "days_7.00_boundary", "days_7.01_above"],
    )
    def test_info_gathering_recovery_window_bva_7days(self, memory_db, elapsed_days, expected_eligible, reason_substring):
        """BVA-INFO-01: Boundary test around 7.0 days clarification recovery window."""
        ref_time = datetime(2026, 8, 30, 12, 0, 0)
        created_at = ref_time - timedelta(days=elapsed_days)

        risk_id = f"risk_info_win_{elapsed_days}"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id=f"evt_win_{elapsed_days}",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
            created_at=created_at,
        )
        insert_risk_event(memory_db, risk)

        res = check_recovery_eligibility(memory_db, risk_id, now=ref_time)
        assert res["eligible"] is expected_eligible
        assert reason_substring in res["reason"]

    @pytest.mark.parametrize(
        "amount,expected_eligible,expected_reason",
        [
            (-0.01, False, "invalid_amount"),   # Below boundary
            (0.00, False, "invalid_amount"),    # Exactly at boundary (amount <= 0)
            (0.01, True, "PASS"),               # Immediately above boundary (amount > 0)
        ],
        ids=["amount_neg_0.01_below", "amount_zero_boundary", "amount_pos_0.01_above"],
    )
    def test_info_gathering_amount_bva_zero(self, memory_db, amount, expected_eligible, expected_reason):
        """BVA-INFO-02: Boundary test around ₹0.00 amount threshold."""
        now = datetime.utcnow()
        risk_id = f"risk_info_amt_{amount}"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id=f"evt_amt_{amount}",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=amount,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=now,
        )
        insert_risk_event(memory_db, risk)

        res = check_recovery_eligibility(memory_db, risk_id, now=now)
        assert res["eligible"] is expected_eligible
        assert res["reason"] == expected_reason


# ==============================================================================
# 6. VOICE RECOVERY BVA TESTS
# Implementation: src/voice.py
# Threshold:
#   - len(clean_phone) < 10: length < 10 -> invalid_phone_number
# ==============================================================================

class TestVoicePhoneLengthBVA:
    """BVA on phone number digit count in check_voice_eligibility()."""

    @pytest.mark.parametrize(
        "phone_number,expected_eligible,expected_reason",
        [
            ("987654321", False, "invalid_phone_number"),      # 9 digits: below boundary (< 10)
            ("9876543210", True, "PASS"),                      # 10 digits: exactly at boundary
            ("19876543210", True, "PASS"),                     # 11 digits: above boundary
        ],
        ids=["digits_9_below", "digits_10_boundary", "digits_11_above"],
    )
    def test_voice_phone_digits_bva_10(self, memory_db, phone_number, expected_eligible, expected_reason):
        """BVA-VOICE-01: Boundary test around 10 digits phone number threshold."""
        now = datetime(2026, 8, 29, 14, 0, 0)  # Allowed daytime hours
        ctx = GuardrailContext(current_time=now, customer_opted_out=False)

        risk_id = f"risk_voice_bva_{phone_number}"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id=f"evt_vbva_{phone_number}",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
            created_at=now,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(
            memory_db,
            RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0),
        )

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(
                conn=memory_db,
                risk_id=risk_id,
                phone_number=phone_number,
                context=ctx,
                now=now,
            )

        assert res["eligible"] is expected_eligible
        assert res["reason"] == expected_reason
