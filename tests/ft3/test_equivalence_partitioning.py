"""
Equivalence Class Partitioning (ECP) Test Suite
Software Testing FT3 - Autonomous AI Revenue Recovery System

This module applies Equivalence Class Partitioning to divide inputs into valid,
invalid, and special equivalence classes, selecting representative inputs
(away from BVA boundary values) to test each distinct operational class.
"""

import os
import json
import hmac
import hashlib
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
    VoiceIntent,
)
from src.db import init_db, insert_risk_event, insert_root_cause
from src.risk_detector import detect_revenue_risk
from src.root_cause import diagnose_root_cause_rules
from src.guardrails import evaluate_guardrails, GuardrailContext
from src.decision_engine import next_action
from src.reconciliation import reconcile_payment_status
from src.receivables import process_b2b_receivable, evaluate_receivable_root_cause
from src.info_gathering import parse_customer_response, check_recovery_eligibility
from src.voice import check_voice_eligibility, extract_hinglish_intent
from src.webhook import process_webhook, extract_reference_id


@pytest.fixture
def memory_db():
    """In-memory SQLite database initialized with fresh schema."""
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


# ==============================================================================
# 1. RISK DETECTOR ECP TESTS
# ==============================================================================

class TestRiskDetectorECP:
    """ECP for Priority classification and EventType-to-RiskType mappings."""

    def test_risk_detector_tier_vip_override(self):
        """ECP-RD-05: Customer tier 'vip' in metadata overrides amount to HIGH priority."""
        event = NormalizedEvent(
            event_id="pay_ecp_vip_tier",
            event_type="payment_failed",
            amount=750.0,  # Below 2500, but customer_tier is 'vip'
            customer_id="cust_vip_tier",
            metadata={"customer_tier": "vip"},
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == Priority.HIGH

    def test_risk_detector_event_type_cart_abandonment(self):
        """ECP-RD-07: Event type 'cart_abandonment' maps to RiskType.CART_ABANDONMENT."""
        event = NormalizedEvent(
            event_id="cart_ecp_01",
            event_type="cart_abandonment",
            amount=3200.0,
            customer_id="cust_cart_01",
        )
        risk = detect_revenue_risk(event)
        assert risk.risk_type == RiskType.CART_ABANDONMENT
        assert risk.priority == Priority.MEDIUM

    def test_risk_detector_event_type_recent_overdue(self):
        """ECP-RD-08: Event type 'recent_overdue' maps to RiskType.RECENT_OVERDUE."""
        event = NormalizedEvent(
            event_id="overdue_ecp_01",
            event_type="recent_overdue",
            amount=4500.0,
            customer_id="cust_overdue_01",
        )
        risk = detect_revenue_risk(event)
        assert risk.risk_type == RiskType.RECENT_OVERDUE
        assert risk.priority == Priority.MEDIUM

    def test_risk_detector_event_type_unknown_fallback(self):
        """ECP-RD-09: Unrecognized event type safely defaults to RiskType.PAYMENT_FAILED."""
        event = NormalizedEvent(
            event_id="unrec_ecp_01",
            event_type="subscription_halted",  # Unrecognized event type
            amount=1500.0,
            customer_id="cust_sub_01",
        )
        risk = detect_revenue_risk(event)
        assert risk.risk_type == RiskType.PAYMENT_FAILED


# ==============================================================================
# 2. ROOT CAUSE ENGINE ECP TESTS
# ==============================================================================

class TestRootCauseECP:
    """ECP for root cause error matching and unmapped fallbacks."""

    def test_root_cause_chronic_risk_profile(self):
        """ECP-RC-07: Customer risk profile 'chronic_non_payer' flags CHRONIC_NON_PAYER."""
        event = NormalizedEvent(
            event_id="pay_rc_chronic",
            event_type="payment_failed",
            amount=5000.0,
            customer_id="cust_chronic",
            error_code="GATEWAY_TIMEOUT",  # Even with gateway error, profile overrides
            metadata={"customer_risk_profile": "chronic_non_payer"},
        )
        risk_event = detect_revenue_risk(event)
        diagnosis = diagnose_root_cause_rules(event, risk_event)
        assert diagnosis.root_cause == RootCauseEnum.CHRONIC_NON_PAYER
        assert diagnosis.confidence == 1.0

    def test_root_cause_unmapped_rule_only(self):
        """ECP-RC-08: Unmapped code and reason in Tier 1 rules returns UNKNOWN (conf: 0.0)."""
        event = NormalizedEvent(
            event_id="pay_rc_unmapped",
            event_type="payment_failed",
            amount=3500.0,
            customer_id="cust_unknown",
            error_code="UNMAPPED_ERR_999",
            error_reason="unidentified_bank_behavior",
        )
        risk_event = detect_revenue_risk(event)
        diagnosis = diagnose_root_cause_rules(event, risk_event)
        assert diagnosis.root_cause == RootCauseEnum.UNKNOWN
        assert diagnosis.confidence == 0.0


# ==============================================================================
# 3. SAFETY GUARDRAILS ECP TESTS
# ==============================================================================

class TestGuardrailsECP:
    """ECP for action categories, mandate scope, and cooldown scope."""

    def test_guardrail_non_retry_non_customer_action_during_dnd_and_cooldown(self):
        """ECP-GR-01: Non-retry, non-customer actions (e.g. ESCALATE) bypass DND and cooldown."""
        ctx = GuardrailContext(
            current_time=datetime(2026, 8, 27, 23, 30, 0),  # DND active (11:30 PM)
            last_retry_at=datetime(2026, 8, 27, 23, 28, 0), # Cooldown active (2 mins ago)
        )
        check = evaluate_guardrails(
            risk_id="risk_gr_esc",
            amount=10000.0,
            action_index=0,
            action_type=ActionType.ESCALATE,
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None

    def test_guardrail_mandate_notice_missing_on_customer_facing_action(self):
        """ECP-GR-03: Mandate notice rule ONLY blocks retries, NOT customer-facing actions."""
        ctx = GuardrailContext(
            is_mandate=True,
            mandate_notice_served=False,
            current_time=datetime(2026, 8, 27, 14, 0, 0),
        )
        check = evaluate_guardrails(
            risk_id="risk_gr_mandate_link",
            amount=2500.0,
            action_index=0,
            action_type=ActionType.PAYMENT_LINK,  # Customer-facing, not a retry
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None

    def test_guardrail_cooldown_active_on_non_retry_action(self):
        """ECP-GR-04: Cooldown active only blocks retry actions, not payment links."""
        now = datetime(2026, 8, 27, 15, 0, 0)
        ctx = GuardrailContext(
            last_retry_at=now - timedelta(minutes=10),  # 600s elapsed (< 14400s)
            current_time=now,
        )
        check = evaluate_guardrails(
            risk_id="risk_gr_cool_link",
            amount=3000.0,
            action_index=1,
            action_type=ActionType.PAYMENT_LINK,  # Payment link is not in RETRY_ACTIONS
            context=ctx,
        )
        assert check.result == GuardrailResultEnum.PASS
        assert check.reason is None


# ==============================================================================
# 4. DECISION ENGINE ECP TESTS
# ==============================================================================

class TestDecisionEngineECP:
    """ECP for B2B playbooks and out-of-bounds action indexing."""

    def test_decision_engine_promise_to_pay_missed_playbook(self):
        """ECP-DE-04: Playbook sequence for promise_to_pay_missed (reminder -> payment_link -> escalate_to_collections)."""
        cause = RootCauseEnum.PROMISE_TO_PAY_MISSED
        assert next_action(cause, 0) == ActionType.REMINDER
        assert next_action(cause, 1) == ActionType.PAYMENT_LINK
        assert next_action(cause, 2) == ActionType.ESCALATE_TO_COLLECTIONS
        assert next_action(cause, 3) is None


# ==============================================================================
# 5. RECONCILIATION ENGINE ECP TESTS
# ==============================================================================

class TestReconciliationECP:
    """ECP for payment states: AUTHORIZED, FAILED with auto-resume, and missing risk_id."""

    def test_reconciliation_authorized_pending_capture(self, memory_db):
        """ECP-RC-02: Payment AUTHORIZED status transitions to authorized_pending_capture (not RECOVERED)."""
        risk = RiskEvent(
            risk_id="risk_recon_auth",
            event_id="evt_recon_auth",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4200.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id="risk_recon_auth",
            forced_status="AUTHORIZED",
        )
        assert res["status"] == "authorized_pending_capture"
        cursor = memory_db.cursor()
        cursor.execute("SELECT status FROM risk_events WHERE risk_id = ?;", ("risk_recon_auth",))
        assert cursor.fetchone()["status"] == EventStatus.IN_PROGRESS.value

    def test_reconciliation_failed_with_auto_resume(self, memory_db):
        """ECP-RC-03: Payment FAILED with auto_resume=True resumes recovery workflow."""
        risk = RiskEvent(
            risk_id="risk_recon_fail_resume",
            event_id="evt_recon_fail_resume",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3000.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(
            memory_db,
            RootCause(risk_id="risk_recon_fail_resume", root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0),
        )

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id="risk_recon_fail_resume",
            forced_status="FAILED",
            auto_resume=True,
        )
        assert res["status"] == "reconciled_failed"
        assert res["workflow_resumed"] is True
        assert res["workflow_result"] is not None

    def test_reconciliation_non_existent_risk_id(self, memory_db):
        """ECP-RC-05: Reconciliation on unknown risk_id safely returns status: 'not_found'."""
        res = reconcile_payment_status(
            conn=memory_db,
            risk_id="risk_non_existent_999",
            forced_status="CAPTURED",
        )
        assert res["status"] == "not_found"
        assert res["risk_id"] == "risk_non_existent_999"


# ==============================================================================
# 6. B2B RECEIVABLES ECP TESTS
# ==============================================================================

class TestB2BReceivablesECP:
    """ECP for B2B feature flag, enterprise tier priority, and aging calculation."""

    def test_b2b_receivables_disabled_flag_raises(self, memory_db):
        """ECP-B2B-01: B2B_ENABLED=False raises PermissionError."""
        now = datetime.utcnow()
        receivable_data = {
            "receivable_id": "rec_flag_test",
            "customer_id": "cust_b2b_flag",
            "invoice_id": "inv_flag",
            "amount_due": 10000.0,
            "due_date": now.isoformat(),
        }
        with patch.dict(os.environ, {"B2B_ENABLED": "false"}):
            with pytest.raises(PermissionError, match="B2B Receivables Recovery is disabled"):
                process_b2b_receivable(memory_db, receivable_data, now=now)

    def test_b2b_enterprise_tier_priority_high(self, memory_db):
        """ECP-B2B-02: Enterprise customer tier receives HIGH priority even when amount < 10,000."""
        now = datetime.utcnow()
        receivable_data = {
            "receivable_id": "rec_ent_tier",
            "customer_id": "cust_b2b_ent",
            "invoice_id": "inv_ent",
            "amount_due": 4500.0,  # Below ₹10,000
            "customer_tier": "ENTERPRISE",
            "due_date": (now - timedelta(days=10)).isoformat(),
        }
        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            res = process_b2b_receivable(memory_db, receivable_data, now=now)
            assert res["status"] == "RECOVERED"
            cursor = memory_db.cursor()
            cursor.execute("SELECT priority FROM risk_events WHERE risk_id = ?;", (res["risk_id"],))
            assert cursor.fetchone()["priority"] == Priority.HIGH.value

    def test_b2b_days_overdue_omitted_auto_calculated(self, memory_db):
        """ECP-B2B-03: When days_overdue is omitted, engine calculates it from due_date."""
        now = datetime.utcnow()
        due_date = now - timedelta(days=25)
        receivable_data = {
            "receivable_id": "rec_calc_days",
            "customer_id": "cust_b2b_calc",
            "invoice_id": "inv_calc",
            "amount_due": 8000.0,
            "due_date": due_date.isoformat(),
            # days_overdue explicitly omitted
        }
        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            res = process_b2b_receivable(memory_db, receivable_data, now=now)
            assert res["status"] == "RECOVERED"
            cursor = memory_db.cursor()
            cursor.execute("SELECT days_overdue FROM receivables WHERE receivable_id = ?;", ("rec_calc_days",))
            assert cursor.fetchone()["days_overdue"] == 25

    def test_b2b_explicit_chronic_tier(self):
        """ECP-B2B-04: Explicit customer_tier 'CHRONIC_NON_PAYER' flags chronic even if days <= 90."""
        now = datetime.utcnow()
        rec = Receivable(
            receivable_id="rec_tier_chronic",
            customer_id="cust_chronic_tier",
            invoice_id="inv_chronic_tier",
            amount_due=15000.0,
            due_date=now - timedelta(days=30),  # Only 30 days overdue (<= 90)
            days_overdue=30,
            customer_tier="CHRONIC_NON_PAYER",
        )
        assert evaluate_receivable_root_cause(rec, now=now) == RootCauseEnum.CHRONIC_NON_PAYER


# ==============================================================================
# 7. CUSTOMER INFORMATION GATHERING ECP TESTS
# ==============================================================================

class TestCustomerInfoGatheringECP:
    """ECP for response parsing and eligibility verification."""

    @pytest.mark.parametrize("empty_input", ["", None, "   "])
    def test_info_gathering_empty_or_none_response(self, empty_input):
        """ECP-INFO-03: Empty, None, or whitespace-only response safely returns None."""
        assert parse_customer_response(empty_input) is None

    def test_info_gathering_non_existent_risk_id(self, memory_db):
        """ECP-INFO-04: Recovery eligibility check on non-existent risk_id returns False."""
        res = check_recovery_eligibility(memory_db, "risk_ghost_001")
        assert res["eligible"] is False
        assert res["reason"] == "risk_event_not_found"

    def test_info_gathering_already_escalated(self, memory_db):
        """ECP-INFO-05: Transaction with status ESCALATED is ineligible for info recovery."""
        risk = RiskEvent(
            risk_id="risk_already_esc",
            event_id="evt_already_esc",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.HIGH,
            status=EventStatus.ESCALATED,
        )
        insert_risk_event(memory_db, risk)
        res = check_recovery_eligibility(memory_db, "risk_already_esc")
        assert res["eligible"] is False
        assert res["reason"] == "already_escalated"


# ==============================================================================
# 8. VOICE RECOVERY ENGINE ECP TESTS
# ==============================================================================

class TestVoiceEngineECP:
    """ECP for phone validation, risk eligibility, and intent extraction."""

    @pytest.mark.parametrize("invalid_phone", [None, 1234567890, ""])
    def test_voice_non_string_phone_rejected(self, memory_db, invalid_phone):
        """ECP-VOICE-01: Non-string, None, or empty phone input rejected as invalid_phone_number."""
        now = datetime(2026, 8, 29, 14, 0, 0)
        ctx = GuardrailContext(current_time=now)
        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_v_1", invalid_phone, context=ctx, now=now)
        assert res["eligible"] is False
        assert res["reason"] == "invalid_phone_number"

    def test_voice_formatted_phone_with_punctuation(self, memory_db):
        """ECP-VOICE-02: Formatted phone string with country code and punctuation successfully validated."""
        now = datetime(2026, 8, 29, 14, 0, 0)
        ctx = GuardrailContext(current_time=now)
        risk = RiskEvent(
            risk_id="risk_voice_format",
            event_id="evt_v_fmt",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(
            memory_db,
            RootCause(risk_id="risk_voice_format", root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0),
        )

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(
                conn=memory_db,
                risk_id="risk_voice_format",
                phone_number="+91 (987) 654-3210",  # 12 digits after stripping formatting
                context=ctx,
                now=now,
            )
        assert res["eligible"] is True
        assert res["reason"] == "PASS"

    def test_voice_non_existent_risk_event(self, memory_db):
        """ECP-VOICE-03: Voice call on missing risk event returns risk_event_not_found."""
        now = datetime(2026, 8, 29, 14, 0, 0)
        ctx = GuardrailContext(current_time=now)
        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_voice_ghost", "+919876543210", context=ctx, now=now)
        assert res["eligible"] is False
        assert res["reason"] == "risk_event_not_found"

    def test_voice_invalid_risk_status(self, memory_db):
        """ECP-VOICE-04: Risk event with status ESCALATED is ineligible for voice outreach."""
        now = datetime(2026, 8, 29, 14, 0, 0)
        ctx = GuardrailContext(current_time=now)
        risk = RiskEvent(
            risk_id="risk_voice_failed_status",
            event_id="evt_v_fail_stat",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.ESCALATED,  # Status in {RECOVERED, ESCALATED}
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_voice_failed_status", "+919876543210", context=ctx, now=now)
        assert res["eligible"] is False
        assert res["reason"] == "invalid_status:ESCALATED"

    def test_voice_human_only_chronic_non_payer(self, memory_db):
        """ECP-VOICE-05: CHRONIC_NON_PAYER root cause blocks autonomous voice outreach."""
        now = datetime(2026, 8, 29, 14, 0, 0)
        ctx = GuardrailContext(current_time=now)
        risk = RiskEvent(
            risk_id="risk_voice_chronic",
            event_id="evt_v_chronic",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(
            memory_db,
            RootCause(risk_id="risk_voice_chronic", root_cause=RootCauseEnum.CHRONIC_NON_PAYER, confidence=1.0),
        )

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = check_voice_eligibility(memory_db, "risk_voice_chronic", "+919876543210", context=ctx, now=now)
        assert res["eligible"] is False
        assert res["reason"] == "human_only_case:chronic_non_payer"

    def test_voice_unsupported_transcript_human_fallback(self):
        """ECP-VOICE-06: Ambiguous / unsupported voice transcript defaults to SPEAK_TO_HUMAN."""
        intent = extract_hinglish_intent("aaj mausam kaisa hai mujhe weather batao")
        assert intent == VoiceIntent.SPEAK_TO_HUMAN


# ==============================================================================
# 9. WEBHOOK PROCESSING & PROVENANCE ECP TESTS
# ==============================================================================

class TestWebhookECP:
    """ECP for webhook signature headers, payload parsing, and reference provenance."""

    def test_webhook_missing_signature_header_rejected(self, memory_db):
        """ECP-WH-03: Missing signature header raises ValueError('Invalid webhook signature')."""
        with pytest.raises(ValueError, match="Invalid webhook signature"):
            process_webhook(
                conn=memory_db,
                raw_body=json.dumps({"event": "payment.captured"}),
                headers={},  # Missing signature header
                webhook_secret="test_secret",
            )

    def test_webhook_malformed_json_body_rejected(self, memory_db):
        """ECP-WH-04: Non-JSON raw body with valid HMAC signature raises ValueError('Invalid JSON webhook payload')."""
        secret = "test_secret"
        malformed_body = "malformed_json{key: value"
        sig = hmac.new(secret.encode(), malformed_body.encode(), hashlib.sha256).hexdigest()
        headers = {"x-razorpay-signature": sig}

        with pytest.raises(ValueError, match="Invalid JSON webhook payload"):
            process_webhook(
                conn=memory_db,
                raw_body=malformed_body,
                headers=headers,
                webhook_secret=secret,
            )

    def test_webhook_order_receipt_provenance(self):
        """ECP-WH-06: Provenance correctly extracted from order.entity.receipt."""
        payload = {
            "payload": {
                "order": {
                    "entity": {
                        "receipt": "risk_rcpt_order_123",
                    }
                }
            }
        }
        assert extract_reference_id(payload) == "risk_rcpt_order_123"

    def test_webhook_payment_link_reference_provenance(self):
        """ECP-WH-07: Provenance correctly extracted from payment_link.entity.reference_id."""
        payload = {
            "payload": {
                "payment_link": {
                    "entity": {
                        "reference_id": "risk_plink_ref_456",
                    }
                }
            }
        }
        assert extract_reference_id(payload) == "risk_plink_ref_456"

    def test_webhook_unattributed_payload_returns_none(self):
        """ECP-WH-08: Payload without risk_ reference ID returns None (unattributed quarantine)."""
        payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_external_789",
                        "notes": {"custom_tag": "no_risk_ref"},
                    }
                }
            }
        }
        assert extract_reference_id(payload) is None
