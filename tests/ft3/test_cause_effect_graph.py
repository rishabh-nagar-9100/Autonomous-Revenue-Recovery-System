"""
Cause-Effect Graph (CEG) Test Suite
Software Testing FT3 - Autonomous AI Revenue Recovery System

This module implements specification-based Cause-Effect Graph Testing.
It validates the multi-variable Boolean logic, intermediate combinational gates,
priority masking rules, and cause -> effect transitions defined in
docs/testing/CAUSE_EFFECT_GRAPH.md.
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
    ReceivableStatusEnum,
)
from src.db import init_db, insert_risk_event, insert_root_cause, get_risk_event
from src.risk_detector import detect_revenue_risk
from src.root_cause import diagnose_root_cause_rules
from src.guardrails import evaluate_guardrails, GuardrailContext
from src.reconciliation import reconcile_payment_status
from src.receivables import process_b2b_receivable, evaluate_receivable_root_cause
from src.voice import check_voice_eligibility
from src.info_gathering import request_customer_info


@pytest.fixture
def memory_db():
    """In-memory SQLite database initialized with fresh schema."""
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


# ==============================================================================
# 1. GUARDRAILS CAUSE-EFFECT GRAPH TESTS
# Subsystem: src/guardrails.py
# Specification: docs/testing/CAUSE_EFFECT_GRAPH.md § 2
# Validates Boolean combinations (AND/OR/NOT) and priority masking cascades
# ==============================================================================

class TestGuardrailsCauseEffect:
    """Cause-Effect validation for Deterministic Guardrail priority sequence."""

    def test_ceg_g01_retry_cap_masks_all_subsequent_violations(self):
        """
        Causes:
          C1: True (attempt_number=5 > 4)
          C2: True (is_mandate=True)
          C3: False (mandate_notice_served=False)
          C4: True (action_type=SMART_RETRY)
          C5: True (last_retry_at exists)
          C6: True (elapsed=100s < 4h)
          C8: True (hour=23 outside 9-20 DND)
          C9: True (customer_opted_out=True)
          C10: True (amount=100,000 > 50,000)
        Intermediate:
          I1 = True (Retry cap breached)
        Effect:
          E1: BLOCK (retry_cap_exceeded) - masks E2, E3, E4, E5, E6.
        """
        now = datetime(2026, 10, 8, 23, 0, 0)
        ctx = GuardrailContext(
            attempt_number=5,
            is_mandate=True,
            mandate_notice_served=False,
            last_retry_at=now - timedelta(seconds=100),
            current_time=now,
            customer_opted_out=True,
        )
        check = evaluate_guardrails(
            risk_id="risk_ceg_01",
            amount=100000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "retry_cap_exceeded"

    def test_ceg_g02_mandate_requires_all_three_conditions_and_gate(self):
        """
        Gate: I2 = C2 (is_mandate) AND NOT C3 (mandate_notice_served) AND C4 (is_retry_action)
        If any input is False, I2 is False:
          - is_mandate=True, notice_served=True, is_retry=True -> NOT blocked by mandate
          - is_mandate=True, notice_served=False, action=PAYMENT_LINK (not retry) -> NOT blocked by mandate
        """
        now = datetime(2026, 10, 8, 14, 0, 0)

        # Sub-case A: Notice IS served (NOT C3 is False) -> I2 False -> PASS
        ctx_served = GuardrailContext(
            attempt_number=1,
            is_mandate=True,
            mandate_notice_served=True,
            current_time=now,
        )
        check_a = evaluate_guardrails(
            risk_id="risk_ceg_02a",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx_served,
        )
        assert check_a.result == GuardrailResultEnum.PASS

        # Sub-case B: Notice NOT served, but action is PAYMENT_LINK (C4 is False) -> I2 False -> PASS
        ctx_not_served = GuardrailContext(
            attempt_number=1,
            is_mandate=True,
            mandate_notice_served=False,
            current_time=now,
        )
        check_b = evaluate_guardrails(
            risk_id="risk_ceg_02b",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx_not_served,
        )
        assert check_b.result == GuardrailResultEnum.PASS

        # Sub-case C: All 3 True -> I2 True -> E2 BLOCK (mandate_notice_required)
        check_c = evaluate_guardrails(
            risk_id="risk_ceg_02c",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx_not_served,
        )
        assert check_c.result == GuardrailResultEnum.BLOCK
        assert check_c.reason == "mandate_notice_required"

    def test_ceg_g03_mandate_masks_cooldown_and_dnd(self):
        """
        Rule 2 (mandate_notice_required) masks Rule 3 (cooldown) and Rule 4 (DND).
        Causes: C1=F, C2=T, C3=F, C4=T, C5=T, C6=T (cooldown active), C8=T (night DND).
        Effect: E2 (mandate_notice_required).
        """
        now = datetime(2026, 10, 8, 22, 0, 0)
        ctx = GuardrailContext(
            attempt_number=2,
            is_mandate=True,
            mandate_notice_served=False,
            last_retry_at=now - timedelta(minutes=30),  # cooldown active
            current_time=now,
        )
        check = evaluate_guardrails(
            risk_id="risk_ceg_03",
            amount=2000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "mandate_notice_required"

    def test_ceg_g04_cooldown_requires_retry_action_and_elapsed_lt_threshold(self):
        """
        Gate: I3 = C5 (last_retry_at is not None) AND C6 (elapsed < 14400) AND C4 (action in RETRY_ACTIONS).
        Tests that cooldown triggers only for retry actions within 4 hours.
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        ctx = GuardrailContext(
            attempt_number=2,
            last_retry_at=now - timedelta(hours=2),  # 2 hours elapsed < 4h
            current_time=now,
        )
        # SMART_RETRY -> Cooldown triggers
        check_retry = evaluate_guardrails(
            risk_id="risk_ceg_04a",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check_retry.result == GuardrailResultEnum.BLOCK
        assert check_retry.reason == "cooldown_active"

        # PAYMENT_LINK -> Cooldown condition C4 False -> Passes to next rule
        check_link = evaluate_guardrails(
            risk_id="risk_ceg_04b",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx,
        )
        assert check_link.result == GuardrailResultEnum.PASS

    def test_ceg_g05_cooldown_elapsed_ge_threshold_allows_next_rule(self):
        """
        When elapsed >= 4h (C6 is False), I3 is False, allowing retry action to pass.
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        ctx = GuardrailContext(
            attempt_number=2,
            last_retry_at=now - timedelta(hours=4, minutes=1),  # elapsed > 4h
            current_time=now,
        )
        check = evaluate_guardrails(
            risk_id="risk_ceg_05",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None

    def test_ceg_g06_dnd_requires_customer_facing_action_and_night_hour(self):
        """
        Gate: I4 = C7 (action in CUSTOMER_FACING) AND C8 (hour < 9 or hour >= 20)
        Customer-facing action (REMINDER) at 21:00 -> E4: BLOCK (dnd_hours).
        Customer-facing action (REMINDER) at 12:00 -> NOT blocked by DND.
        """
        night_time = datetime(2026, 10, 8, 21, 30, 0)
        day_time = datetime(2026, 10, 8, 12, 0, 0)

        ctx_night = GuardrailContext(current_time=night_time)
        check_night = evaluate_guardrails(
            risk_id="risk_ceg_06a",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.REMINDER,
            context=ctx_night,
        )
        assert check_night.result == GuardrailResultEnum.BLOCK
        assert check_night.reason == "dnd_hours"

        ctx_day = GuardrailContext(current_time=day_time)
        check_day = evaluate_guardrails(
            risk_id="risk_ceg_06b",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.REMINDER,
            context=ctx_day,
        )
        assert check_day.result == GuardrailResultEnum.PASS

    def test_ceg_g07_dnd_backend_retry_immunity(self):
        """
        Cause-Effect Immunity: C8=True (hour=23) but C7=False (SMART_RETRY is not customer facing).
        I4 is False -> Backend retry passes during DND hours.
        """
        night_time = datetime(2026, 10, 8, 23, 0, 0)
        ctx = GuardrailContext(current_time=night_time)
        check = evaluate_guardrails(
            risk_id="risk_ceg_07",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS

    def test_ceg_g08_customer_opt_out_requires_customer_facing_action(self):
        """
        Gate: I5 = C9 (customer_opted_out) AND C7 (customer facing action).
        During business hours (14:00):
          - DISCOUNT_NUDGE with opted-out customer -> E5: BLOCK (customer_opted_out)
          - DELAYED_RETRY with opted-out customer -> C7 False -> I5 False -> PASS
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        ctx = GuardrailContext(current_time=now, customer_opted_out=True)

        check_nudge = evaluate_guardrails(
            risk_id="risk_ceg_08a",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.DISCOUNT_NUDGE,
            context=ctx,
        )
        assert check_nudge.result == GuardrailResultEnum.BLOCK
        assert check_nudge.reason == "customer_opted_out"

        check_retry = evaluate_guardrails(
            risk_id="risk_ceg_08b",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.DELAYED_RETRY,
            context=ctx,
        )
        assert check_retry.result == GuardrailResultEnum.PASS

    def test_ceg_g09_dnd_masks_customer_opt_out(self):
        """
        Priority Masking: Rule 4 (dnd_hours) evaluates before Rule 5 (customer_opted_out).
        When both DND is active (22:00) and customer is opted out:
        Effect must be E4: BLOCK (dnd_hours).
        """
        night_time = datetime(2026, 10, 8, 22, 0, 0)
        ctx = GuardrailContext(current_time=night_time, customer_opted_out=True)
        check = evaluate_guardrails(
            risk_id="risk_ceg_09",
            amount=1000.0,
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "dnd_hours"

    def test_ceg_g10_human_approval_only_evaluates_when_higher_rules_pass(self):
        """
        Gate: I6 = C10 (amount > threshold).
        When amount=75,000 > 50,000:
          - If higher rules pass -> E6: BLOCK (amount_requires_human_approval)
          - If attempt=5 (C1=True) -> E1 (retry_cap_exceeded) masks human approval
        """
        now = datetime(2026, 10, 8, 14, 0, 0)

        # Unmasked: passes rules 1-5, blocked by rule 6
        ctx_pass_1_to_5 = GuardrailContext(attempt_number=1, current_time=now)
        check_high_amount = evaluate_guardrails(
            risk_id="risk_ceg_10a",
            amount=75000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx_pass_1_to_5,
        )
        assert check_high_amount.result == GuardrailResultEnum.BLOCK
        assert check_high_amount.reason == "amount_requires_human_approval"

        # Masked: attempt=5 -> blocked by rule 1
        ctx_attempt_5 = GuardrailContext(attempt_number=5, current_time=now)
        check_masked = evaluate_guardrails(
            risk_id="risk_ceg_10b",
            amount=75000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx_attempt_5,
        )
        assert check_masked.result == GuardrailResultEnum.BLOCK
        assert check_masked.reason == "retry_cap_exceeded"

    def test_ceg_g11_all_guardrails_pass_clean_execution(self):
        """
        Cause combination where all intermediate violation gates I1..I6 evaluate to False.
        Effect: E7: PASS (Guardrails satisfied).
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        ctx = GuardrailContext(
            attempt_number=1,
            is_mandate=False,
            last_retry_at=None,
            current_time=now,
            customer_opted_out=False,
        )
        check = evaluate_guardrails(
            risk_id="risk_ceg_11",
            amount=15000.0,
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None


# ==============================================================================
# 2. RISK DETECTOR CAUSE-EFFECT GRAPH TESTS
# Subsystem: src/risk_detector.py
# Specification: docs/testing/CAUSE_EFFECT_GRAPH.md § 3
# ==============================================================================

class TestRiskDetectorCauseEffect:
    """Cause-Effect validation for Revenue Risk Detector priority & type mapping."""

    def test_ceg_r01_vip_flag_or_tier_triggers_high_priority_regardless_of_amount(self):
        """
        Gate: I_VIP = C2 (is_vip) OR C3 (customer_tier=='vip')
        I_High = C1 (amount >= 10000) OR I_VIP.
        Even if amount is small (₹100), VIP triggers Priority.HIGH.
        """
        # C2=True (metadata is_vip)
        event_vip_meta = NormalizedEvent(
            event_id="evt_vip_01",
            event_type="payment_failed",
            amount=100.0,
            customer_id="cust_01",
            timestamp=datetime.utcnow(),
            metadata={"is_vip": True},
        )
        risk_a = detect_revenue_risk(event_vip_meta)
        assert risk_a.priority == Priority.HIGH

        # C3=True (customer_tier=='vip')
        event_vip_tier = NormalizedEvent(
            event_id="evt_vip_02",
            event_type="payment_failed",
            amount=150.0,
            customer_id="cust_02",
            timestamp=datetime.utcnow(),
            metadata={"customer_tier": "vip"},
        )
        risk_b = detect_revenue_risk(event_vip_tier)
        assert risk_b.priority == Priority.HIGH

    def test_ceg_r02_amount_ge_10000_triggers_high_priority_without_vip(self):
        """
        Gate: I_High = C1 (amount >= 10000) OR I_VIP.
        C1=True, C2=False, C3=False -> Priority.HIGH.
        """
        event = NormalizedEvent(
            event_id="evt_high_01",
            event_type="payment_failed",
            amount=12000.0,
            customer_id="cust_high",
            timestamp=datetime.utcnow(),
            metadata={},
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == Priority.HIGH

    def test_ceg_r03_medium_priority_requires_not_high_and_amount_ge_2500(self):
        """
        Gate: I_Med = NOT I_High AND C4 (amount >= 2500).
        Amount=5000, non-VIP -> Priority.MEDIUM.
        """
        event = NormalizedEvent(
            event_id="evt_med_01",
            event_type="payment_failed",
            amount=5000.0,
            customer_id="cust_med",
            timestamp=datetime.utcnow(),
            metadata={"is_vip": False, "customer_tier": "standard"},
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == Priority.MEDIUM

    def test_ceg_r04_low_priority_requires_not_high_and_not_medium(self):
        """
        Gate: I_Low = NOT I_High AND NOT C4 (amount < 2500).
        Amount=1500, non-VIP -> Priority.LOW.
        """
        event = NormalizedEvent(
            event_id="evt_low_01",
            event_type="payment_failed",
            amount=1500.0,
            customer_id="cust_low",
            timestamp=datetime.utcnow(),
            metadata={},
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == Priority.LOW

    def test_ceg_r05_risk_type_mapping_and_fallback_logic(self):
        """
        Validates cause-effect mappings for event_type -> RiskType:
          C5 (payment_failed) -> E4 (PAYMENT_FAILED)
          C6 (cart_abandonment) -> E5 (CART_ABANDONMENT)
          C7 (recent_overdue) -> E6 (RECENT_OVERDUE)
          All other unrecognized -> Fallback to E4 (PAYMENT_FAILED)
        """
        types = [
            ("payment_failed", RiskType.PAYMENT_FAILED),
            ("cart_abandonment", RiskType.CART_ABANDONMENT),
            ("recent_overdue", RiskType.RECENT_OVERDUE),
            ("subscription_lapse", RiskType.PAYMENT_FAILED),  # Fallback
            ("order_cancelled", RiskType.PAYMENT_FAILED),     # Fallback
        ]
        for evt_type, expected_risk_type in types:
            evt = NormalizedEvent(
                event_id=f"evt_{evt_type}",
                event_type=evt_type,
                amount=1000.0,
                customer_id="cust_t",
                timestamp=datetime.utcnow(),
                metadata={},
            )
            risk = detect_revenue_risk(evt)
            assert risk.risk_type == expected_risk_type


# ==============================================================================
# 3. ROOT CAUSE ENGINE CAUSE-EFFECT GRAPH TESTS
# Subsystem: src/root_cause.py
# Specification: docs/testing/CAUSE_EFFECT_GRAPH.md § 4
# ==============================================================================

class TestRootCauseCauseEffect:
    """Cause-Effect validation for Tier 1 Root Cause diagnostic cascades."""

    def test_ceg_c01_chronic_metadata_overrides_bank_timeout_error(self):
        """
        Priority Masking:
        Gate: I_ChronicMeta = C1 OR C2 OR C3.
        When C1=True (is_chronic_defaulter) and C5=True (error_code='GATEWAY_TIMEOUT'):
        Effect is E1: CHRONIC_NON_PAYER (NOT BANK_TIMEOUT).
        """
        evt = NormalizedEvent(
            event_id="evt_rc_01",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_c1",
            timestamp=datetime.utcnow(),
            error_code="GATEWAY_TIMEOUT",
            error_reason="gateway_timeout",
            metadata={"is_chronic_defaulter": True},
        )
        risk = detect_revenue_risk(evt)
        rc = diagnose_root_cause_rules(evt, risk)
        assert rc.root_cause == RootCauseEnum.CHRONIC_NON_PAYER
        assert rc.confidence == 1.0

    def test_ceg_c02_consecutive_failures_ge_4_overrides_nsf_error(self):
        """
        When C3=True (consecutive_failures=4 >= 4) and C6=True (error_reason='insufficient_funds'):
        Effect is E1: CHRONIC_NON_PAYER (NOT NSF).
        """
        evt = NormalizedEvent(
            event_id="evt_rc_02",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_c2",
            timestamp=datetime.utcnow(),
            error_reason="insufficient_funds",
            metadata={"consecutive_failures": 4},
        )
        risk = detect_revenue_risk(evt)
        rc = diagnose_root_cause_rules(evt, risk)
        assert rc.root_cause == RootCauseEnum.CHRONIC_NON_PAYER

    def test_ceg_c03_bank_timeout_code_or_reason_without_chronic(self):
        """
        When NOT ChronicMeta and (C4 OR C5) is True:
        Effect is E2: BANK_TIMEOUT.
        """
        # Reason match
        evt_reason = NormalizedEvent(
            event_id="evt_rc_03a",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_c3a",
            timestamp=datetime.utcnow(),
            error_reason="bank_technical_error",
            metadata={},
        )
        risk_a = detect_revenue_risk(evt_reason)
        rc_a = diagnose_root_cause_rules(evt_reason, risk_a)
        assert rc_a.root_cause == RootCauseEnum.BANK_TIMEOUT

        # Code match
        evt_code = NormalizedEvent(
            event_id="evt_rc_03b",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_c3b",
            timestamp=datetime.utcnow(),
            error_code="BANK_OFFLINE",
            metadata={},
        )
        risk_b = detect_revenue_risk(evt_code)
        rc_b = diagnose_root_cause_rules(evt_code, risk_b)
        assert rc_b.root_cause == RootCauseEnum.BANK_TIMEOUT

    def test_ceg_c04_nsf_code_or_reason_without_chronic(self):
        """
        When NOT ChronicMeta and NOT Timeout and (C6 OR C7) is True:
        Effect is E3: NSF.
        """
        evt = NormalizedEvent(
            event_id="evt_rc_04",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_c4",
            timestamp=datetime.utcnow(),
            error_code="INSUFFICIENT_FUNDS",
            metadata={},
        )
        risk = detect_revenue_risk(evt)
        rc = diagnose_root_cause_rules(evt, risk)
        assert rc.root_cause == RootCauseEnum.NSF

    def test_ceg_c05_expired_card_code_or_reason_without_chronic(self):
        """
        When NOT ChronicMeta and NOT Timeout and NOT NSF and (C8 OR C9) is True:
        Effect is E4: EXPIRED_CARD.
        """
        evt = NormalizedEvent(
            event_id="evt_rc_05",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_c5",
            timestamp=datetime.utcnow(),
            error_reason="card_expired",
            metadata={},
        )
        risk = detect_revenue_risk(evt)
        rc = diagnose_root_cause_rules(evt, risk)
        assert rc.root_cause == RootCauseEnum.EXPIRED_CARD

    def test_ceg_c06_unmapped_error_without_llm_produces_unknown(self):
        """
        When no known error reason or code matches:
        Effect is E7: UNKNOWN with confidence 0.0.
        """
        evt = NormalizedEvent(
            event_id="evt_rc_06",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_c6",
            timestamp=datetime.utcnow(),
            error_code="UNEXPECTED_THIRD_PARTY_ANOMALY",
            error_reason="vendor_hiccup",
            metadata={},
        )
        risk = detect_revenue_risk(evt)
        rc = diagnose_root_cause_rules(evt, risk)
        assert rc.root_cause == RootCauseEnum.UNKNOWN
        assert rc.confidence == 0.0


# ==============================================================================
# 4. RECONCILIATION STATE MACHINE CAUSE-EFFECT GRAPH TESTS
# Subsystem: src/reconciliation.py
# Specification: docs/testing/CAUSE_EFFECT_GRAPH.md § 5
# ==============================================================================

class TestReconciliationCauseEffect:
    """Cause-Effect validation for Payment Reconciliation state transitions and invariants."""

    def test_ceg_m01_terminal_recovered_invariant_masks_all_incoming_statuses(self, memory_db):
        """
        Monotonic Terminal State Invariant:
        Cause: C1=True (current_status == 'RECOVERED').
        Inbound: C2=True ('SUCCESS') or C4=True ('FAILED').
        Effect: E1: status='already_recovered', DB status remains RECOVERED.
        """
        risk_event = RiskEvent(
            risk_id="risk_rec_01",
            event_id="evt_rec_01",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.HIGH,
            status=EventStatus.RECOVERED,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk_event)

        # Attempt to mark SUCCESS again
        res_succ = reconcile_payment_status(memory_db, risk_id="risk_rec_01", forced_status="SUCCESS")
        assert res_succ["status"] == "already_recovered"

        # Attempt to revert to FAILED
        res_fail = reconcile_payment_status(memory_db, risk_id="risk_rec_01", forced_status="FAILED")
        assert res_fail["status"] == "already_recovered"

        # Verify DB remained untouched
        updated = get_risk_event(memory_db, "risk_rec_01")
        assert updated.status == EventStatus.RECOVERED

    def test_ceg_m02_success_or_captured_triggers_recovery_outcome(self, memory_db):
        """
        Cause: NOT C1 AND C2=True (forced_status in {'RECOVERED', 'SUCCESS', 'CAPTURED'}).
        Effect: E2: status='reconciled', new_status='RECOVERED', outcome record updated.
        """
        risk_event = RiskEvent(
            risk_id="risk_rec_02",
            event_id="evt_rec_02",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3500.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk_event)

        res = reconcile_payment_status(memory_db, risk_id="risk_rec_02", forced_status="CAPTURED")
        assert res["status"] == "reconciled"
        assert res["new_status"] == EventStatus.RECOVERED.value
        assert res["amount_recovered"] == 3500.0

        updated = get_risk_event(memory_db, "risk_rec_02")
        assert updated.status == EventStatus.RECOVERED

    def test_ceg_m03_authorized_status_marks_pending_capture_not_recovered(self, memory_db):
        """
        Financial State Semantics:
        Cause: NOT C1 AND NOT C2 AND C3=True (forced_status == 'AUTHORIZED').
        Effect: E3: status='authorized_pending_capture', risk event remains NOT RECOVERED.
        """
        risk_event = RiskEvent(
            risk_id="risk_rec_03",
            event_id="evt_rec_03",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2000.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk_event)

        res = reconcile_payment_status(memory_db, risk_id="risk_rec_03", forced_status="AUTHORIZED")
        assert res["status"] == "authorized_pending_capture"

        updated = get_risk_event(memory_db, "risk_rec_03")
        assert updated.status == EventStatus.IN_PROGRESS  # NOT RECOVERED

    def test_ceg_m04_failed_status_transitions_to_in_progress(self, memory_db):
        """
        Cause: NOT C1..C3 AND C4=True (forced_status == 'FAILED') AND C7=False (auto_resume=False).
        Effect: E4: status='reconciled_failed', new_status='IN_PROGRESS', workflow_resumed=False.
        """
        risk_event = RiskEvent(
            risk_id="risk_rec_04",
            event_id="evt_rec_04",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.DETECTED,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk_event)

        res = reconcile_payment_status(
            memory_db,
            risk_id="risk_rec_04",
            forced_status="FAILED",
            auto_resume=False,
        )
        assert res["status"] == "reconciled_failed"
        assert res["new_status"] == EventStatus.IN_PROGRESS.value
        assert res["workflow_resumed"] is False

    def test_ceg_m05_timeout_exhausted_by_attempts_ge_3(self, memory_db):
        """
        Timeout Rule:
        Gate: I_Timeout = C5 (attempt_count >= 3) OR C6 (elapsed_hours >= 24.0).
        With forced_status='PENDING':
        C5=True (attempts=3), C6=False (elapsed=2.0h) -> E5: status='escalated_timeout', new_status='ESCALATED'.
        """
        risk_event = RiskEvent(
            risk_id="risk_rec_05",
            event_id="evt_rec_05",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1500.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk_event)

        res = reconcile_payment_status(
            memory_db,
            risk_id="risk_rec_05",
            forced_status="PENDING",
            attempt_count=3,
            elapsed_hours=2.0,
        )
        assert res["status"] == "escalated_timeout"
        assert res["new_status"] == EventStatus.ESCALATED.value

        updated = get_risk_event(memory_db, "risk_rec_05")
        assert updated.status == EventStatus.ESCALATED

    def test_ceg_m06_timeout_exhausted_by_elapsed_hours_ge_24(self, memory_db):
        """
        With forced_status='PENDING':
        C5=False (attempts=1), C6=True (elapsed=24.5h >= 24) -> E5: escalated_timeout.
        """
        risk_event = RiskEvent(
            risk_id="risk_rec_06",
            event_id="evt_rec_06",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1500.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk_event)

        res = reconcile_payment_status(
            memory_db,
            risk_id="risk_rec_06",
            forced_status="PENDING",
            attempt_count=1,
            elapsed_hours=24.5,
        )
        assert res["status"] == "escalated_timeout"
        assert res["new_status"] == EventStatus.ESCALATED.value

    def test_ceg_m07_pending_polling_when_both_attempts_and_hours_under_threshold(self, memory_db):
        """
        With forced_status='PENDING':
        When C5 is False (attempts=2 < 3) AND C6 is False (hours=12.0 < 24.0):
        Effect: E6: status='pending_reconciliation'.
        """
        risk_event = RiskEvent(
            risk_id="risk_rec_07",
            event_id="evt_rec_07",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1500.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk_event)

        res = reconcile_payment_status(
            memory_db,
            risk_id="risk_rec_07",
            forced_status="PENDING",
            attempt_count=2,
            elapsed_hours=12.0,
        )
        assert res["status"] == "pending_reconciliation"
        assert res["attempts"] == 2
        assert res["elapsed_hours"] == 12.0


# ==============================================================================
# 5. B2B RECEIVABLES ENGINE CAUSE-EFFECT GRAPH TESTS
# Subsystem: src/receivables.py
# Specification: docs/testing/CAUSE_EFFECT_GRAPH.md § 6
# ==============================================================================

class TestB2BReceivablesCauseEffect:
    """Cause-Effect validation for B2B Receivables recovery pipeline."""

    def test_ceg_b01_disabled_feature_flag_raises_permission_error(self, memory_db):
        """
        Cause: C1=True (not is_b2b_enabled()).
        Effect: E1: PermissionError("B2B Receivables Recovery is disabled").
        """
        with patch.dict(os.environ, {"B2B_ENABLED": "false"}):
            with pytest.raises(PermissionError, match="B2B Receivables Recovery is disabled"):
                process_b2b_receivable(
                    memory_db,
                    {
                        "receivable_id": "rec_01",
                        "customer_id": "cust_b1",
                        "invoice_id": "inv_01",
                        "amount_due": 5000.0,
                        "due_date": "2026-10-01T00:00:00",
                    },
                )

    def test_ceg_b02_missed_p2p_overrides_chronic_tier_and_days_overdue(self):
        """
        Priority Masking:
        Gate: I_P2PMissed = C2 (P2P date present) AND C3 (now > P2P date).
        When P2P is missed, it overrides customer_tier='CHRONIC_NON_PAYER' and days_overdue=120 > 90.
        Effect: E2: PROMISE_TO_PAY_MISSED.
        """
        now = datetime(2026, 10, 8, 12, 0, 0)
        p2p_date = now - timedelta(days=2)  # In the past

        rec = Receivable(
            receivable_id="rec_b02",
            customer_id="cust_b2",
            invoice_id="inv_b2",
            amount_due=50000.0,
            due_date=now - timedelta(days=120),
            days_overdue=120,
            status=ReceivableStatusEnum.OPEN,
            customer_tier="CHRONIC_NON_PAYER",
            promise_to_pay_date=p2p_date,
            created_at=now,
        )
        rc = evaluate_receivable_root_cause(rec, now=now)
        assert rc == RootCauseEnum.PROMISE_TO_PAY_MISSED

    def test_ceg_b03_chronic_tier_triggers_immediate_escalation(self, memory_db):
        """
        Gate: NOT I_P2PMissed AND I_Chronic (C4: tier == 'CHRONIC_NON_PAYER' OR C5: days_overdue > 90).
        Effect: E3: CHRONIC_NON_PAYER -> Status ESCALATED immediately.
        """
        now = datetime(2026, 10, 8, 12, 0, 0)
        payload = {
            "receivable_id": "rec_b03",
            "customer_id": "cust_b3",
            "invoice_id": "inv_b3",
            "amount_due": 15000.0,
            "due_date": (now - timedelta(days=30)).isoformat(),
            "customer_tier": "CHRONIC_NON_PAYER",
            "days_overdue": 30,
        }
        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            res = process_b2b_receivable(memory_db, payload, now=now)
            assert res["status"] == "ESCALATED"
            assert res["root_cause"] == RootCauseEnum.CHRONIC_NON_PAYER.value

            updated = get_risk_event(memory_db, "risk_b2b_rec_b03")
            assert updated.status == EventStatus.ESCALATED

    def test_ceg_b04_days_overdue_gt_90_triggers_immediate_escalation(self, memory_db):
        """
        Cause: C5=True (days_overdue=95 > 90), customer_tier='STANDARD'.
        Effect: E3: CHRONIC_NON_PAYER -> Status ESCALATED.
        """
        now = datetime(2026, 10, 8, 12, 0, 0)
        payload = {
            "receivable_id": "rec_b04",
            "customer_id": "cust_b4",
            "invoice_id": "inv_b4",
            "amount_due": 5000.0,
            "due_date": (now - timedelta(days=95)).isoformat(),
            "customer_tier": "STANDARD",
            "days_overdue": 95,
        }
        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            res = process_b2b_receivable(memory_db, payload, now=now)
            assert res["status"] == "ESCALATED"
            assert res["root_cause"] == RootCauseEnum.CHRONIC_NON_PAYER.value

    def test_ceg_b05_standard_overdue_without_p2p_or_chronic(self, memory_db):
        """
        When NOT I_P2PMissed and NOT I_Chronic:
        Effect: E4: RECEIVABLE_OVERDUE -> Evaluated and processed.
        """
        now = datetime(2026, 10, 8, 12, 0, 0)
        payload = {
            "receivable_id": "rec_b05",
            "customer_id": "cust_b5",
            "invoice_id": "inv_b5",
            "amount_due": 8000.0,
            "due_date": (now - timedelta(days=15)).isoformat(),
            "customer_tier": "STANDARD",
            "days_overdue": 15,
        }
        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            res = process_b2b_receivable(memory_db, payload, now=now)
            assert res["root_cause"] == RootCauseEnum.RECEIVABLE_OVERDUE.value
            assert res["status"] == "RECOVERED"

    def test_ceg_b06_priority_assignment_enterprise_or_amount(self, memory_db):
        """
        Priority Gate: I_High = C6 (amount >= 10000) OR C7 (tier == 'ENTERPRISE').
        - Case A: amount=5000, ENTERPRISE -> Priority.HIGH (C7=True)
        - Case B: amount=15000, STANDARD -> Priority.HIGH (C6=True)
        - Case C: amount=5000, STANDARD -> Priority.MEDIUM (Both False)
        """
        now = datetime(2026, 10, 8, 12, 0, 0)

        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            # Case A: Enterprise tier
            payload_a = {
                "receivable_id": "rec_prio_a",
                "customer_id": "cust_pa",
                "invoice_id": "inv_pa",
                "amount_due": 5000.0,
                "due_date": (now - timedelta(days=10)).isoformat(),
                "customer_tier": "ENTERPRISE",
                "days_overdue": 10,
            }
            process_b2b_receivable(memory_db, payload_a, now=now)
            risk_a = get_risk_event(memory_db, "risk_b2b_rec_prio_a")
            assert risk_a.priority == Priority.HIGH

            # Case B: High amount
            payload_b = {
                "receivable_id": "rec_prio_b",
                "customer_id": "cust_pb",
                "invoice_id": "inv_pb",
                "amount_due": 15000.0,
                "due_date": (now - timedelta(days=10)).isoformat(),
                "customer_tier": "STANDARD",
                "days_overdue": 10,
            }
            process_b2b_receivable(memory_db, payload_b, now=now)
            risk_b = get_risk_event(memory_db, "risk_b2b_rec_prio_b")
            assert risk_b.priority == Priority.HIGH

            # Case C: Medium
            payload_c = {
                "receivable_id": "rec_prio_c",
                "customer_id": "cust_pc",
                "invoice_id": "inv_pc",
                "amount_due": 5000.0,
                "due_date": (now - timedelta(days=10)).isoformat(),
                "customer_tier": "STANDARD",
                "days_overdue": 10,
            }
            process_b2b_receivable(memory_db, payload_c, now=now)
            risk_c = get_risk_event(memory_db, "risk_b2b_rec_prio_c")
            assert risk_c.priority == Priority.MEDIUM


# ==============================================================================
# 6. AUXILIARY COMMUNICATION ENGINES CAUSE-EFFECT GRAPH TESTS
# Subsystem: src/voice.py & src/info_gathering.py
# Specification: docs/testing/CAUSE_EFFECT_GRAPH.md § 7
# ==============================================================================

class TestVoiceAndInfoGatheringCauseEffect:
    """Cause-Effect validation for Voice eligibility and Customer Info Gathering."""

    def test_ceg_v01_voice_disabled_flag_blocks_voice(self, memory_db):
        """
        Cause: C1=True (not is_voice_enabled()).
        Effect: Ineligible with reason 'voice_disabled'.
        """
        with patch.dict(os.environ, {"VOICE_ENABLED": "false"}):
            res = check_voice_eligibility(memory_db, "risk_v01", "+919876543210")
            assert res["eligible"] is False
            assert res["reason"] == "voice_disabled"

    def test_ceg_v02_customer_opt_out_blocks_voice(self, memory_db):
        """
        Cause: C2=True (customer_opted_out).
        Effect: Ineligible with reason 'customer_opted_out'.
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        ctx = GuardrailContext(current_time=now, customer_opted_out=True)
        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_v02", "+919876543210", context=ctx)
            assert res["eligible"] is False
            assert res["reason"] == "customer_opted_out"

    def test_ceg_v03_dnd_hours_blocks_voice(self, memory_db):
        """
        Cause: C3=True (is_dnd_hours: 22:00 outside 9-20).
        Effect: Ineligible with reason 'dnd_hours'.
        """
        night_time = datetime(2026, 10, 8, 22, 0, 0)
        ctx = GuardrailContext(current_time=night_time, customer_opted_out=False)
        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_v03", "+919876543210", context=ctx)
            assert res["eligible"] is False
            assert res["reason"] == "dnd_hours"

    def test_ceg_v04_invalid_phone_number_blocks_voice(self, memory_db):
        """
        Cause: C4=True (clean digits < 10).
        Effect: Ineligible with reason 'invalid_phone_number'.
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        ctx = GuardrailContext(current_time=now, customer_opted_out=False)
        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_v04", "12345", context=ctx)
            assert res["eligible"] is False
            assert res["reason"] == "invalid_phone_number"

    def test_ceg_v05_terminal_status_blocks_voice(self, memory_db):
        """
        Cause: C5=True (risk_event.status == RECOVERED).
        Effect: Ineligible with reason 'invalid_status:RECOVERED'.
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        risk = RiskEvent(
            risk_id="risk_v05",
            event_id="evt_v05",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.RECOVERED,
            created_at=now,
        )
        insert_risk_event(memory_db, risk)
        ctx = GuardrailContext(current_time=now)
        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_v05", "+919876543210", context=ctx)
            assert res["eligible"] is False
            assert res["reason"] == "invalid_status:RECOVERED"

    def test_ceg_v06_chronic_non_payer_is_human_only_blocks_voice(self, memory_db):
        """
        Cause: C6=True (diagnosed root cause is CHRONIC_NON_PAYER).
        Effect: Ineligible with reason 'human_only_case:chronic_non_payer'.
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        risk = RiskEvent(
            risk_id="risk_v06",
            event_id="evt_v06",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
            created_at=now,
        )
        insert_risk_event(memory_db, risk)
        rc = RootCause(
            risk_id="risk_v06",
            root_cause=RootCauseEnum.CHRONIC_NON_PAYER,
            confidence=1.0,
            source="rule",
            created_at=now,
        )
        insert_root_cause(memory_db, rc)

        ctx = GuardrailContext(current_time=now)
        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_v06", "+919876543210", context=ctx)
            assert res["eligible"] is False
            assert res["reason"] == "human_only_case:chronic_non_payer"

    def test_ceg_i01_info_gathering_attempt_limit_exceeded_triggers_escalation(self, memory_db):
        """
        Cause: C2=True (existing info_request exists for risk_id).
        Effect: E_i2: Blocked & Escalated with reason 'info_gathering_attempt_limit_exceeded'.
        """
        now = datetime(2026, 10, 8, 14, 0, 0)
        risk = RiskEvent(
            risk_id="risk_i01",
            event_id="evt_i01",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=now,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            # First request succeeds
            res1 = request_customer_info(memory_db, "risk_i01", amount=1000.0, customer_id="cust_i1", now=now)
            assert res1["status"] == "requested"

            # Second request blocked and escalated
            res2 = request_customer_info(memory_db, "risk_i01", amount=1000.0, customer_id="cust_i1", now=now)
            assert res2["status"] == "blocked"
            assert res2["reason"] == "info_gathering_attempt_limit_exceeded"
            assert res2["escalated"] is True

            updated = get_risk_event(memory_db, "risk_i01")
            assert updated.status == EventStatus.ESCALATED

    def test_ceg_i02_info_gathering_guardrail_block_triggers_escalation(self, memory_db):
        """
        Cause: C3=True (guardrail blocked due to DND hours or customer opt out).
        Effect: E_i3: Blocked & Escalated with reason 'guardrail_blocked:dnd_hours'.
        """
        night_time = datetime(2026, 10, 8, 22, 0, 0)
        risk = RiskEvent(
            risk_id="risk_i02",
            event_id="evt_i02",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=night_time,
        )
        insert_risk_event(memory_db, risk)

        ctx_night = GuardrailContext(current_time=night_time)
        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            res = request_customer_info(
                memory_db,
                "risk_i02",
                amount=1000.0,
                customer_id="cust_i2",
                context=ctx_night,
                now=night_time,
            )
            assert res["status"] == "guardrail_blocked"
            assert res["reason"] == "guardrail_blocked:dnd_hours"
            assert res["escalated"] is True

            updated = get_risk_event(memory_db, "risk_i02")
            assert updated.status == EventStatus.ESCALATED

