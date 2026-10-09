"""
Decision Table Testing Suite
Software Testing FT3 - Autonomous AI Revenue Recovery System

This module implements automated Decision Table tests corresponding directly
to the rules specified in docs/testing/DECISION_TABLES.md and traced in
docs/testing/DECISION_TABLE_TEST_MATRIX.md.

Tables Covered:
  1. Guardrails Decision Table (DT-G01 to DT-G11)
  2. Root Cause & Playbook Decision Table (DT-R01 to DT-R11)
  3. Payment Reconciliation Decision Table (DT-M01 to DT-M09)
  4. B2B Receivables Decision Table (DT-B01 to DT-B08)
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
from src.decision_engine import next_action
from src.guardrails import evaluate_guardrails, GuardrailContext
from src.reconciliation import reconcile_payment_status
from src.receivables import process_b2b_receivable


@pytest.fixture
def memory_db():
    """In-memory SQLite database initialized with fresh schema."""
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


# ==============================================================================
# 1. GUARDRAILS DECISION TABLE TESTS
# Specification: docs/testing/DECISION_TABLES.md § 2
# Rules: DT-G01 to DT-G11
# ==============================================================================

class TestGuardrailsDecisionTable:
    """Decision Table testing of Guardrail rule hierarchy and masking."""

    @pytest.mark.parametrize(
        "rule_id,attempt_num,is_mandate,notice_served,action_type,elapsed_sec,hour,opted_out,amount,expected_result,expected_reason",
        [
            # DT-G01: Attempt > 4 masks all other restrictions
            (
                "DT-G01",
                5, True, False, ActionType.SMART_RETRY, 100, 23, True, 100000.0,
                GuardrailResultEnum.BLOCK, "retry_cap_exceeded",
            ),
            # DT-G02: Mandate notice required masks cooldown, DND, opt-out, amount
            (
                "DT-G02",
                1, True, False, ActionType.SMART_RETRY, 100, 23, True, 100000.0,
                GuardrailResultEnum.BLOCK, "mandate_notice_required",
            ),
            # DT-G03: Mandate notice served, cooldown active masks DND and amount
            (
                "DT-G03",
                1, True, True, ActionType.SMART_RETRY, 3600, 14, False, 100000.0,
                GuardrailResultEnum.BLOCK, "cooldown_active",
            ),
            # DT-G04: Cooldown active on standard retry action masks opt-out and amount
            (
                "DT-G04",
                1, False, True, ActionType.SMART_RETRY, 3600, 14, True, 10000.0,
                GuardrailResultEnum.BLOCK, "cooldown_active",
            ),
            # DT-G05: Customer-facing action during DND window masks opt-out and amount
            (
                "DT-G05",
                1, False, True, ActionType.PAYMENT_LINK, None, 22, True, 75000.0,
                GuardrailResultEnum.BLOCK, "dnd_hours",
            ),
            # DT-G06: Customer-facing action during daytime with opted-out customer masks amount
            (
                "DT-G06",
                1, False, True, ActionType.REMINDER, None, 14, True, 75000.0,
                GuardrailResultEnum.BLOCK, "customer_opted_out",
            ),
            # DT-G07: Amount exceeds threshold when all higher rules pass
            (
                "DT-G07",
                1, False, True, ActionType.PAYMENT_LINK, None, 14, False, 75000.0,
                GuardrailResultEnum.BLOCK, "amount_requires_human_approval",
            ),
            # DT-G08: Backend retry action immune to DND hours
            (
                "DT-G08",
                1, False, True, ActionType.SMART_RETRY, None, 23, False, 10000.0,
                GuardrailResultEnum.PASS, None,
            ),
            # DT-G09: Backend retry action immune to customer opt-out
            (
                "DT-G09",
                1, False, True, ActionType.SMART_RETRY, None, 14, True, 10000.0,
                GuardrailResultEnum.PASS, None,
            ),
            # DT-G10: Mandate without notice does not block non-retry action (PAYMENT_LINK)
            (
                "DT-G10",
                1, True, False, ActionType.PAYMENT_LINK, None, 14, False, 10000.0,
                GuardrailResultEnum.PASS, None,
            ),
            # DT-G11: Clean customer-facing action within all limits
            (
                "DT-G11",
                1, False, True, ActionType.PAYMENT_LINK, None, 14, False, 10000.0,
                GuardrailResultEnum.PASS, None,
            ),
        ],
    )
    def test_dt_guardrails_rules(
        self,
        rule_id,
        attempt_num,
        is_mandate,
        notice_served,
        action_type,
        elapsed_sec,
        hour,
        opted_out,
        amount,
        expected_result,
        expected_reason,
    ):
        """Validates Decision Table rules DT-G01 through DT-G11 for Guardrail priority order."""
        eval_time = datetime(2026, 10, 8, hour, 0, 0)
        last_retry = eval_time - timedelta(seconds=elapsed_sec) if elapsed_sec is not None else None

        ctx = GuardrailContext(
            attempt_number=attempt_num,
            is_mandate=is_mandate,
            mandate_notice_served=notice_served,
            last_retry_at=last_retry,
            current_time=eval_time,
            customer_opted_out=opted_out,
        )

        check = evaluate_guardrails(
            risk_id=f"risk_{rule_id}",
            amount=amount,
            action_index=0,
            action_type=action_type,
            context=ctx,
        )

        assert check.result == expected_result, f"Rule {rule_id}: expected result {expected_result}, got {check.result}"
        assert check.reason == expected_reason, f"Rule {rule_id}: expected reason {expected_reason}, got {check.reason}"


# ==============================================================================
# 2. ROOT CAUSE & DECISION ENGINE PLAYBOOK TESTS
# Specification: docs/testing/DECISION_TABLES.md § 3
# Rules: DT-R01 to DT-R11
# ==============================================================================

class TestRootCauseAndPlaybookDecisionTable:
    """Decision Table testing of Root Cause diagnosis and Playbook action lookup."""

    @pytest.mark.parametrize(
        "rule_id,consec_failures,err_code,err_reason,evt_type,action_idx,expected_cause,expected_action",
        [
            # DT-R01: Chronic non-payer metadata overrides timeout error code
            ("DT-R01", 4, "GATEWAY_TIMEOUT", "gateway_timeout", "payment_failed", 0, RootCauseEnum.CHRONIC_NON_PAYER, None),
            # DT-R02: Bank timeout step 0 -> smart_retry
            ("DT-R02", 0, "GATEWAY_TIMEOUT", None, "payment_failed", 0, RootCauseEnum.BANK_TIMEOUT, ActionType.SMART_RETRY),
            # DT-R03: Bank timeout step 1 -> payment_link
            ("DT-R03", 0, "GATEWAY_TIMEOUT", None, "payment_failed", 1, RootCauseEnum.BANK_TIMEOUT, ActionType.PAYMENT_LINK),
            # DT-R04: Bank timeout step 2 -> exhausted (None)
            ("DT-R04", 0, "GATEWAY_TIMEOUT", None, "payment_failed", 2, RootCauseEnum.BANK_TIMEOUT, None),
            # DT-R05: NSF step 0 -> delayed_retry
            ("DT-R05", 0, None, "insufficient_funds", "payment_failed", 0, RootCauseEnum.NSF, ActionType.DELAYED_RETRY),
            # DT-R06: NSF step 1 -> payment_link
            ("DT-R06", 0, None, "insufficient_funds", "payment_failed", 1, RootCauseEnum.NSF, ActionType.PAYMENT_LINK),
            # DT-R07: Expired card step 0 -> payment_link
            ("DT-R07", 0, None, "card_expired", "payment_failed", 0, RootCauseEnum.EXPIRED_CARD, ActionType.PAYMENT_LINK),
            # DT-R08: Expired card step 1 -> reminder
            ("DT-R08", 0, None, "card_expired", "payment_failed", 1, RootCauseEnum.EXPIRED_CARD, ActionType.REMINDER),
            # DT-R09: Cart abandonment step 0 -> discount_nudge
            ("DT-R09", 0, None, None, "cart_abandonment", 0, RootCauseEnum.CART_ABANDONMENT, ActionType.DISCOUNT_NUDGE),
            # DT-R10: Recent overdue step 0 -> reminder
            ("DT-R10", 0, None, None, "recent_overdue", 0, RootCauseEnum.RECENT_OVERDUE, ActionType.REMINDER),
            # DT-R11: Unmapped error reason/code -> UNKNOWN, no action
            ("DT-R11", 0, "CUSTOM_THIRD_PARTY_FAIL", "unknown_gateway_error", "payment_failed", 0, RootCauseEnum.UNKNOWN, None),
        ],
    )
    def test_dt_root_cause_playbook_rules(
        self,
        rule_id,
        consec_failures,
        err_code,
        err_reason,
        evt_type,
        action_idx,
        expected_cause,
        expected_action,
    ):
        """Validates Decision Table rules DT-R01 through DT-R11 for Root Cause and Playbook dispatch."""
        evt = NormalizedEvent(
            event_id=f"evt_{rule_id}",
            event_type=evt_type,
            amount=5000.0,
            customer_id="cust_dt_r",
            timestamp=datetime.utcnow(),
            error_code=err_code,
            error_reason=err_reason,
            metadata={"consecutive_failures": consec_failures},
        )
        risk = detect_revenue_risk(evt)
        diag = diagnose_root_cause_rules(evt, risk)

        assert diag.root_cause == expected_cause, f"Rule {rule_id}: expected root cause {expected_cause}, got {diag.root_cause}"

        action = next_action(diag.root_cause, action_idx)
        assert action == expected_action, f"Rule {rule_id}: expected action {expected_action}, got {action}"


# ==============================================================================
# 3. RECONCILIATION STATE MACHINE TESTS
# Specification: docs/testing/DECISION_TABLES.md § 4
# Rules: DT-M01 to DT-M09
# ==============================================================================

class TestReconciliationDecisionTable:
    """Decision Table testing of Reconciliation status arbitrations and timeouts."""

    @pytest.mark.parametrize(
        "rule_id,init_status,inbound_status,auto_resume,attempt_cnt,elapsed_hrs,expected_result_status,expected_db_status",
        [
            # DT-M01: Terminal RECOVERED invariant masks all inbound events
            ("DT-M01", EventStatus.RECOVERED, "FAILED", False, 1, 0.0, "already_recovered", EventStatus.RECOVERED.value),
            # DT-M02: Confirmed CAPTURED status marks RECOVERED
            ("DT-M02", EventStatus.IN_PROGRESS, "CAPTURED", False, 1, 0.0, "reconciled", EventStatus.RECOVERED.value),
            # DT-M03: AUTHORIZED status marks pending capture, NOT RECOVERED
            ("DT-M03", EventStatus.IN_PROGRESS, "AUTHORIZED", False, 1, 0.0, "authorized_pending_capture", EventStatus.IN_PROGRESS.value),
            # DT-M04: Confirmed FAILED with auto-resume marks IN_PROGRESS
            ("DT-M04", EventStatus.DETECTED, "FAILED", True, 1, 0.0, "reconciled_failed", EventStatus.IN_PROGRESS.value),
            # DT-M05: Confirmed FAILED without auto-resume marks IN_PROGRESS
            ("DT-M05", EventStatus.DETECTED, "FAILED", False, 1, 0.0, "reconciled_failed", EventStatus.IN_PROGRESS.value),
            # DT-M06: Polling timeout exhausted by attempts >= 3
            ("DT-M06", EventStatus.IN_PROGRESS, "PENDING", False, 3, 2.0, "escalated_timeout", EventStatus.ESCALATED.value),
            # DT-M07: Polling timeout exhausted by elapsed hours >= 24.0
            ("DT-M07", EventStatus.IN_PROGRESS, "PENDING", False, 1, 24.5, "escalated_timeout", EventStatus.ESCALATED.value),
            # DT-M08: Polling timeout exhausted by both attempts and hours
            ("DT-M08", EventStatus.IN_PROGRESS, "PENDING", False, 4, 25.0, "escalated_timeout", EventStatus.ESCALATED.value),
            # DT-M09: Polling within limits remains pending_reconciliation
            ("DT-M09", EventStatus.IN_PROGRESS, "PENDING", False, 2, 12.0, "pending_reconciliation", EventStatus.IN_PROGRESS.value),
        ],
    )
    def test_dt_reconciliation_rules(
        self,
        memory_db,
        rule_id,
        init_status,
        inbound_status,
        auto_resume,
        attempt_cnt,
        elapsed_hrs,
        expected_result_status,
        expected_db_status,
    ):
        """Validates Decision Table rules DT-M01 through DT-M09 for Payment Reconciliation."""
        risk_id = f"risk_{rule_id}"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id=f"evt_{rule_id}",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2500.0,
            priority=Priority.MEDIUM,
            status=init_status,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(
            memory_db,
            RootCause(
                risk_id=risk_id,
                root_cause=RootCauseEnum.BANK_TIMEOUT,
                confidence=1.0,
                created_at=datetime.utcnow(),
            ),
        )

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id=risk_id,
            forced_status=inbound_status,
            attempt_count=attempt_cnt,
            elapsed_hours=elapsed_hrs,
            auto_resume=auto_resume,
        )

        assert res["status"] == expected_result_status, f"Rule {rule_id}: expected status {expected_result_status}, got {res['status']}"

        updated = get_risk_event(memory_db, risk_id)
        assert updated.status.value == expected_db_status, f"Rule {rule_id}: expected DB status {expected_db_status}, got {updated.status.value}"


# ==============================================================================
# 4. B2B RECEIVABLES RECOVERY TESTS
# Specification: docs/testing/DECISION_TABLES.md § 5
# Rules: DT-B01 to DT-B08
# ==============================================================================

class TestB2BReceivablesDecisionTable:
    """Decision Table testing of B2B Receivables priority and root cause handling."""

    @pytest.mark.parametrize(
        "rule_id,b2b_enabled,p2p_offset_days,customer_tier,days_overdue,amount,expected_cause,expected_prio,expected_status",
        [
            # DT-B01: B2B feature flag disabled raises PermissionError
            ("DT-B01", False, None, "STANDARD", 10, 5000.0, None, None, "PERMISSION_ERROR"),
            # DT-B02: Missed P2P date overrides chronic tier, amount >= 10k -> HIGH priority
            ("DT-B02", True, -2, "CHRONIC_NON_PAYER", 100, 15000.0, RootCauseEnum.PROMISE_TO_PAY_MISSED.value, Priority.HIGH, "RECOVERED"),
            # DT-B03: Missed P2P date, standard tier, amount < 10k -> MEDIUM priority
            ("DT-B03", True, -2, "STANDARD", 10, 5000.0, RootCauseEnum.PROMISE_TO_PAY_MISSED.value, Priority.MEDIUM, "RECOVERED"),
            # DT-B04: Chronic tier without P2P, amount >= 10k -> Immediate ESCALATED, HIGH priority
            ("DT-B04", True, None, "CHRONIC_NON_PAYER", 30, 12000.0, RootCauseEnum.CHRONIC_NON_PAYER.value, Priority.HIGH, "ESCALATED"),
            # DT-B05: Overdue > 90 days without P2P, amount < 10k -> Immediate ESCALATED, MEDIUM priority
            ("DT-B05", True, None, "STANDARD", 95, 4000.0, RootCauseEnum.CHRONIC_NON_PAYER.value, Priority.MEDIUM, "ESCALATED"),
            # DT-B06: Standard overdue, Enterprise customer tier -> HIGH priority
            ("DT-B06", True, None, "ENTERPRISE", 15, 5000.0, RootCauseEnum.RECEIVABLE_OVERDUE.value, Priority.HIGH, "RECOVERED"),
            # DT-B07: Standard overdue, Standard customer tier, amount >= 10k -> HIGH priority
            ("DT-B07", True, None, "STANDARD", 15, 15000.0, RootCauseEnum.RECEIVABLE_OVERDUE.value, Priority.HIGH, "RECOVERED"),
            # DT-B08: Standard overdue, Standard customer tier, amount < 10k -> MEDIUM priority
            ("DT-B08", True, None, "STANDARD", 15, 5000.0, RootCauseEnum.RECEIVABLE_OVERDUE.value, Priority.MEDIUM, "RECOVERED"),
        ],
    )
    def test_dt_b2b_receivables_rules(
        self,
        memory_db,
        rule_id,
        b2b_enabled,
        p2p_offset_days,
        customer_tier,
        days_overdue,
        amount,
        expected_cause,
        expected_prio,
        expected_status,
    ):
        """Validates Decision Table rules DT-B01 through DT-B08 for B2B Receivables Recovery."""
        now = datetime(2026, 10, 8, 12, 0, 0)
        p2p_date = (now + timedelta(days=p2p_offset_days)).isoformat() if p2p_offset_days is not None else None
        due_date = (now - timedelta(days=days_overdue)).isoformat()

        payload = {
            "receivable_id": f"rec_{rule_id}",
            "customer_id": f"cust_{rule_id}",
            "invoice_id": f"inv_{rule_id}",
            "amount_due": amount,
            "due_date": due_date,
            "days_overdue": days_overdue,
            "customer_tier": customer_tier,
            "promise_to_pay_date": p2p_date,
        }

        flag_str = "true" if b2b_enabled else "false"
        with patch.dict(os.environ, {"B2B_ENABLED": flag_str}):
            if expected_status == "PERMISSION_ERROR":
                with pytest.raises(PermissionError, match="B2B Receivables Recovery is disabled"):
                    process_b2b_receivable(memory_db, payload, now=now)
            else:
                res = process_b2b_receivable(memory_db, payload, now=now)
                assert res["root_cause"] == expected_cause, f"Rule {rule_id}: expected root cause {expected_cause}, got {res['root_cause']}"
                assert res["status"] == expected_status, f"Rule {rule_id}: expected status {expected_status}, got {res['status']}"

                risk = get_risk_event(memory_db, f"risk_b2b_rec_{rule_id}")
                assert risk.priority == expected_prio, f"Rule {rule_id}: expected priority {expected_prio}, got {risk.priority}"
