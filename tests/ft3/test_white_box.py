"""
White Box Testing Suite
Software Testing FT3 - Autonomous AI Revenue Recovery System

This module implements targeted white-box test cases designed to exercise
specific control-flow branches, defensive exception handling paths, and internal
sub-branches documented in docs/testing/WHITE_BOX_ANALYSIS.md and
traced in docs/testing/WHITE_BOX_TRACEABILITY.md.
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
    ExecutionStatusEnum,
    GuardrailResultEnum,
    Receivable,
    ReceivableStatusEnum,
)
from src.db import (
    init_db,
    insert_risk_event,
    insert_root_cause,
    get_risk_event,
    insert_execution,
    get_receivable,
)
from src.guardrails import default_guardrail_time, evaluate_guardrails, GuardrailContext
from src.root_cause import diagnose_root_cause, diagnose_root_cause_rules
from src.reconciliation import reconcile_payment_status
from src.outcome_tracker import handle_outcome, start_recovery_workflow
from src.receivables import process_b2b_receivable
from src.info_gathering import can_request_info
from src.webhook import extract_reference_id, extract_event_id


@pytest.fixture
def memory_db():
    """In-memory SQLite database initialized with fresh schema."""
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


# ==============================================================================
# 1. GUARDRAILS INTERNAL BRANCHES
# ==============================================================================

class TestGuardrailsWhiteBox:
    """White-box branch tests for src/guardrails.py."""

    def test_wb_default_guardrail_time_night_hours(self):
        """
        WB-G12: Exercises line 48 in src/guardrails.py:
        When datetime.now() falls in DND night window (< 9 or >= 20),
        default_guardrail_time replaces the hour with 14:00.
        """
        fake_night_time = datetime(2026, 10, 8, 22, 45, 0)
        with patch("src.guardrails.datetime") as mock_datetime:
            mock_datetime.now.return_value = fake_night_time
            res = default_guardrail_time()
            assert res.hour == 14
            assert res.minute == 0


# ==============================================================================
# 2. ROOT CAUSE ENGINE INTERNAL BRANCHES
# ==============================================================================

class TestRootCauseWhiteBox:
    """White-box branch tests for src/root_cause.py."""

    def test_wb_diagnose_root_cause_llm_disabled_fallback(self):
        """
        WB-R10: Exercises branch 165->176 in src/root_cause.py:
        When use_llm_fallback=False and rule diagnosis is UNKNOWN,
        diagnose_root_cause directly bypasses LLM and returns UNKNOWN with source='rule'.
        """
        evt = NormalizedEvent(
            event_id="evt_wb_rc_01",
            event_type="payment_failed",
            amount=5000.0,
            customer_id="cust_wb_rc",
            timestamp=datetime.utcnow(),
            error_code="UNRECOGNIZED_ANOMALY",
            error_reason="unrecognized_reason",
            metadata={},
        )
        risk = RiskEvent(
            risk_id="risk_wb_rc_01",
            event_id="evt_wb_rc_01",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.DETECTED,
            created_at=datetime.utcnow(),
        )

        diag = diagnose_root_cause(evt, risk, use_llm_fallback=False)
        assert diag.root_cause == RootCauseEnum.UNKNOWN
        assert diag.confidence == 0.0
        assert diag.source == "rule"


# ==============================================================================
# 3. RECONCILIATION INTERNAL BRANCHES & METADATA
# ==============================================================================

class TestReconciliationWhiteBox:
    """White-box branch tests for src/reconciliation.py."""

    def test_wb_reconciliation_missing_risk_event(self, memory_db):
        """
        WB-M01: Exercises line 44 in src/reconciliation.py:
        When risk_id does not exist in the database, returns {'status': 'not_found'}.
        """
        res = reconcile_payment_status(memory_db, risk_id="risk_missing_record")
        assert res["status"] == "not_found"
        assert res["risk_id"] == "risk_missing_record"

    def test_wb_reconciliation_terminal_with_metadata(self, memory_db):
        """
        WB-M03: Exercises lines 58-62 in src/reconciliation.py:
        When current_status is RECOVERED and razorpay_payment_id and webhook_event_id are passed,
        they are safely populated into audit input data.
        """
        risk = RiskEvent(
            risk_id="risk_wb_m_term",
            event_id="evt_wb_m_term",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3000.0,
            priority=Priority.HIGH,
            status=EventStatus.RECOVERED,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk)

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id="risk_wb_m_term",
            forced_status="SUCCESS",
            razorpay_payment_id="pay_wb_123",
            webhook_event_id="evt_wb_123",
            source_event="payment.captured",
        )
        assert res["status"] == "already_recovered"

    def test_wb_reconciliation_capture_with_prior_executions(self, memory_db):
        """
        WB-M05: Exercises lines 104-109 in src/reconciliation.py:
        When executions already exist in the database, reconciliation reads MAX(action_index).
        """
        risk = RiskEvent(
            risk_id="risk_wb_m_exec",
            event_id="evt_wb_m_exec",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4000.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk)

        # Insert execution record with action_index = 2
        from src.models import Execution
        insert_execution(
            memory_db,
            Execution(
                execution_id="exec_wb_01",
                risk_id="risk_wb_m_exec",
                action_index=2,
                action_type=ActionType.PAYMENT_LINK,
                status=ExecutionStatusEnum.SUCCESS,
                executed_at=datetime.utcnow(),
            ),
        )

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id="risk_wb_m_exec",
            forced_status="CAPTURED",
            razorpay_payment_id="pay_wb_exec",
            webhook_event_id="evt_wb_exec",
        )
        assert res["status"] == "reconciled"
        assert res["new_status"] == EventStatus.RECOVERED.value

    def test_wb_reconciliation_failed_with_metadata(self, memory_db):
        """
        Exercises lines 218-222 in src/reconciliation.py:
        When reconciled_status is FAILED, passes razorpay_payment_id and webhook_event_id to audit log.
        """
        risk = RiskEvent(
            risk_id="risk_wb_m_fail",
            event_id="evt_wb_m_fail",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2000.0,
            priority=Priority.LOW,
            status=EventStatus.DETECTED,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk)

        res = reconcile_payment_status(
            conn=memory_db,
            risk_id="risk_wb_m_fail",
            forced_status="FAILED",
            razorpay_payment_id="pay_fail_meta",
            webhook_event_id="evt_fail_meta",
        )
        assert res["status"] == "reconciled_failed"
        assert res["new_status"] == EventStatus.IN_PROGRESS.value


# ==============================================================================
# 4. OUTCOME TRACKER DEFENSIVE GUARDS
# ==============================================================================

class TestOutcomeTrackerWhiteBox:
    """White-box branch tests for src/outcome_tracker.py."""

    def test_wb_handle_outcome_missing_risk_event(self, memory_db):
        """
        WB-O01: Exercises line 90 in src/outcome_tracker.py:
        Raises ValueError when risk event record does not exist.
        """
        with pytest.raises(ValueError, match="Risk event with risk_id 'ghost_risk' not found"):
            handle_outcome(
                conn=memory_db,
                risk_id="ghost_risk",
                action_index=0,
                execution_status=ExecutionStatusEnum.SUCCESS,
            )

    def test_wb_handle_outcome_missing_root_cause(self, memory_db):
        """
        WB-O02: Exercises line 94 in src/outcome_tracker.py:
        Raises ValueError when root cause record for risk_id is missing.
        """
        risk = RiskEvent(
            risk_id="risk_no_rc",
            event_id="evt_no_rc",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk)

        with pytest.raises(ValueError, match="Root cause for risk_id 'risk_no_rc' not found"):
            handle_outcome(
                conn=memory_db,
                risk_id="risk_no_rc",
                action_index=0,
                execution_status=ExecutionStatusEnum.FAILED,
            )

    def test_wb_start_recovery_workflow_validation(self, memory_db):
        """
        WB-O06: Exercises lines 268 & 272 in src/outcome_tracker.py:
        Validates risk_event and root_cause existence before starting workflow.
        """
        with pytest.raises(ValueError, match="not found"):
            start_recovery_workflow(conn=memory_db, risk_id="ghost_start")

        risk = RiskEvent(
            risk_id="risk_no_rc_start",
            event_id="evt_no_rc_start",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime.utcnow(),
        )
        insert_risk_event(memory_db, risk)

        with pytest.raises(ValueError, match="not found"):
            start_recovery_workflow(conn=memory_db, risk_id="risk_no_rc_start")


# ==============================================================================
# 5. B2B RECEIVABLES WORKFLOW ESCALATION
# ==============================================================================

class TestB2BReceivablesWhiteBox:
    """White-box branch tests for src/receivables.py."""

    def test_wb_b2b_process_workflow_escalation(self, memory_db):
        """
        WB-B05: Exercises lines 169-170 in src/receivables.py:
        When a standard B2B receivable workflow terminates in EventStatus.ESCALATED,
        the receivable status is explicitly transitioned to ReceivableStatusEnum.ESCALATED.
        """
        now = datetime(2026, 10, 8, 12, 0, 0)
        payload = {
            "receivable_id": "rec_wb_esc",
            "customer_id": "cust_wb_esc",
            "invoice_id": "inv_wb_esc",
            "amount_due": 5000.0,
            "due_date": (now - timedelta(days=10)).isoformat(),
            "customer_tier": "STANDARD",
            "days_overdue": 10,
        }

        # Simulate all actions failing so that the playbook is exhausted and escalates
        simulated_failures = {0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.FAILED, 2: ExecutionStatusEnum.FAILED}

        with patch.dict(os.environ, {"B2B_ENABLED": "true"}):
            res = process_b2b_receivable(
                conn=memory_db,
                receivable_data=payload,
                simulated_action_outcomes=simulated_failures,
                now=now,
            )
            assert res["status"] == "ESCALATED"

            rec = get_receivable(memory_db, "rec_wb_esc")
            assert rec.status == ReceivableStatusEnum.ESCALATED


# ==============================================================================
# 6. WEBHOOK PROVENANCE & IDENTIFIER EXTRACTION BRANCHES
# ==============================================================================

class TestWebhookWhiteBox:
    """White-box branch tests for src/webhook.py."""

    def test_wb_webhook_extract_ref_non_dict_payload(self):
        """
        WB-W01: Exercises line 37 in src/webhook.py:
        Non-dictionary payload safely returns None without raising an AttributeError.
        """
        assert extract_reference_id(["not", "a", "dict"]) is None
        assert extract_reference_id("raw_string") is None
        assert extract_reference_id(None) is None

    def test_wb_webhook_extract_ref_order_receipt(self):
        """
        WB-W02: Exercises line 73->79 in src/webhook.py:
        Extracts valid risk ID from payload.order.entity.receipt.
        """
        payload = {
            "payload": {
                "order": {
                    "entity": {
                        "receipt": "risk_ord_receipt_99",
                    }
                }
            }
        }
        assert extract_reference_id(payload) == "risk_ord_receipt_99"

    def test_wb_webhook_extract_ref_payment_link_entity_reference(self):
        """
        WB-W03: Exercises line 79->85 in src/webhook.py:
        Extracts valid risk ID from payload.payment_link.entity.reference_id.
        """
        payload = {
            "payload": {
                "payment_link": {
                    "entity": {
                        "reference_id": "risk_plink_ref_88",
                    }
                }
            }
        }
        assert extract_reference_id(payload) == "risk_plink_ref_88"

    def test_wb_webhook_extract_ref_payment_link_notes(self):
        """
        WB-W04: Exercises line 87 in src/webhook.py:
        Extracts valid risk ID from payload.payment_link.entity.notes.
        """
        payload = {
            "payload": {
                "payment_link": {
                    "entity": {
                        "notes": {
                            "risk_id": "risk_plink_notes_77",
                        }
                    }
                }
            }
        }
        assert extract_reference_id(payload) == "risk_plink_notes_77"

    def test_wb_webhook_extract_ref_top_level_notes(self):
        """
        WB-W05: Exercises line 92 in src/webhook.py:
        Extracts valid risk ID from top-level notes dictionary.
        """
        payload = {
            "notes": {
                "reference_id": "risk_top_notes_66",
            }
        }
        assert extract_reference_id(payload) == "risk_top_notes_66"

    def test_wb_webhook_extract_ref_top_level_keys(self):
        """
        WB-W06: Exercises line 98 in src/webhook.py:
        Extracts valid risk ID from top-level receipt attribute.
        """
        payload = {
            "receipt": "risk_top_rcpt_55",
        }
        assert extract_reference_id(payload) == "risk_top_rcpt_55"

    def test_wb_webhook_extract_event_id_fallbacks(self):
        """
        WB-W07: Exercises lines 128-138 in src/webhook.py:
        Extracts event ID from payload['id'], payment.entity['id'], or fallback MD5 hash.
        """
        # Case A: payload['id']
        assert extract_event_id({}, {"id": "evt_top_11"}) == "evt_top_11"

        # Case B: payload.payment.entity['id']
        assert extract_event_id({}, {"payload": {"payment": {"entity": {"id": "pay_entity_22"}}}}) == "evt_pay_entity_22"

        # Case C: Fallback MD5 hash
        hashed_id = extract_event_id({}, {"arbitrary_data": "value"})
        assert hashed_id.startswith("evt_hash_")


# ==============================================================================
# 7. INFO GATHERING FEATURE FLAG GATES
# ==============================================================================

class TestInfoGatheringWhiteBox:
    """White-box branch tests for src/info_gathering.py."""

    def test_wb_info_gathering_disabled_flag(self, memory_db):
        """
        WB-I01: Exercises line 36 in src/info_gathering.py:
        When INFO_GATHERING_ENABLED is false, can_request_info returns False immediately.
        """
        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "false"}):
            assert can_request_info(memory_db, "risk_any_id") is False
