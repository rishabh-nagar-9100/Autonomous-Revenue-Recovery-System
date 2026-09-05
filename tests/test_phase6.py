import pytest
import sqlite3
import json
from datetime import datetime
from src.models import (
    ExecutionStatusEnum,
    EventStatus,
    RootCauseEnum,
)
from src.db import (
    init_db,
    get_audit_trail_for_risk,
)
from src.pipeline import process_payment_failed_event
from src.guardrails import GuardrailContext
from src.outcome_tracker import start_recovery_workflow
from src.audit import log_audit, get_audit_trail


DAYTIME_CONTEXT = GuardrailContext(
    current_time=datetime(2026, 8, 27, 14, 0, 0)
)


@pytest.fixture
def in_memory_db():
    """Provides an initialized in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestAuditTrail:
    def test_log_audit_appends_and_serializes_structured_json(self, in_memory_db):
        entry = log_audit(
            conn=in_memory_db,
            risk_id="risk_audit_test_01",
            layer="test_layer",
            input_data={"amount": 5000.0, "reason": "test"},
            output_data={"status": "APPROVED", "flags": [1, 2]},
            decision="test_decision_made",
        )

        assert entry.id is not None
        assert entry.risk_id == "risk_audit_test_01"
        assert entry.layer == "test_layer"
        assert entry.decision == "test_decision_made"

        # Verify valid JSON
        in_obj = json.loads(entry.input_json)
        assert in_obj["amount"] == 5000.0

        out_obj = json.loads(entry.output_json)
        assert out_obj["status"] == "APPROVED"
        assert out_obj["flags"] == [1, 2]

        trail = get_audit_trail(in_memory_db, "risk_audit_test_01")
        assert len(trail) == 1
        assert trail[0].decision == "test_decision_made"

    def test_append_only_behavior_preserves_past_entries(self, in_memory_db):
        entry_1 = log_audit(
            conn=in_memory_db,
            risk_id="risk_append_01",
            layer="layer_1",
            input_data={"step": 1},
            output_data={"step_1_done": True},
            decision="step_1_complete",
        )
        entry_2 = log_audit(
            conn=in_memory_db,
            risk_id="risk_append_01",
            layer="layer_2",
            input_data={"step": 2},
            output_data={"step_2_done": True},
            decision="step_2_complete",
        )

        trail = get_audit_trail(in_memory_db, "risk_append_01")
        assert len(trail) == 2
        assert trail[0].id == entry_1.id
        assert trail[0].decision == "step_1_complete"
        assert trail[1].id == entry_2.id
        assert trail[1].decision == "step_2_complete"

    def test_full_recovered_journey_audit_reconstruction(self, in_memory_db):
        """
        Critical Phase 6 Acceptance Test 1:
        Reconstruct complete journey for multi-step recovered transaction:
        ingestion -> risk_detection -> root_cause -> action_selected -> guardrail_pass ->
        action_executed (fail) -> outcome_recorded -> action_selected -> guardrail_pass ->
        action_executed (success) -> outcome_recorded -> revenue_recovered
        """
        raw_webhook = {
            "entity": "event",
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_audit_rec_001",
                        "amount": 1800000,  # 18,000 INR
                        "currency": "INR",
                        "customer_id": "cust_audit_rec",
                        "error_code": "GATEWAY_ERROR",
                        "error_reason": "payment_timed_out",
                        "error_description": "Bank network timeout during transaction.",
                    }
                }
            },
        }

        # 1. Pipeline ingestion, risk detection, and root cause diagnosis
        norm_ev, risk_ev, rc = process_payment_failed_event(raw_webhook, in_memory_db)
        risk_id = risk_ev.risk_id

        # 2. Closed-loop recovery workflow (smart_retry fails, payment_link succeeds)
        res = start_recovery_workflow(
            conn=in_memory_db,
            risk_id=risk_id,
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={
                0: ExecutionStatusEnum.FAILED,
                1: ExecutionStatusEnum.SUCCESS,
            },
            customer_id="cust_audit_rec",
        )
        assert res.final_status == EventStatus.IN_PROGRESS

        from src.reconciliation import reconcile_payment_status
        reconcile_payment_status(in_memory_db, risk_id, forced_status="RECOVERED")

        # 3. Query complete audit history
        audit_trail = get_audit_trail(in_memory_db, risk_id)
        decisions = [entry.decision for entry in audit_trail]
        layers = [entry.layer for entry in audit_trail]

        expected_decisions = [
            "event_normalized",
            "revenue_at_risk_detected",
            "root_cause_identified",
            "action_selected",
            "guardrail_pass",
            "action_executed",
            "outcome_recorded",
            "action_selected",
            "guardrail_pass",
            "action_executed",
            "outcome_recorded",
            "action_execution_succeeded",
            "payment_status_reconciled_recovered",
        ]

        assert decisions == expected_decisions
        assert layers == [
            "ingestion",
            "revenue_risk_detector",
            "root_cause_engine",
            "decision_engine",
            "guardrail",
            "action_executor",
            "outcome_tracker",
            "decision_engine",
            "guardrail",
            "action_executor",
            "outcome_tracker",
            "outcome_tracker",
            "reconciliation_engine",
        ]

        # Verify all audit entries have valid timestamps, non-empty JSON inputs and outputs
        for entry in audit_trail:
            assert entry.risk_id == risk_id
            assert json.loads(entry.input_json) is not None
            assert json.loads(entry.output_json) is not None
            assert isinstance(entry.timestamp, datetime)

    def test_guardrail_blocked_and_escalated_journey_audit_reconstruction(self, in_memory_db):
        """
        Critical Phase 6 Acceptance Test 2:
        Reconstruct complete journey for guardrail-blocked transaction:
        ingestion -> risk_detection -> root_cause -> action_0 -> guardrail_pass ->
        exec_0 (fail) -> outcome -> action_1 -> guardrail_block (dnd_hours) -> escalated
        Verify blocked action is NOT executed in action_executor audit log.
        """
        raw_webhook = {
            "entity": "event",
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_audit_block_001",
                        "amount": 500000,
                        "currency": "INR",
                        "customer_id": "cust_audit_block",
                        "error_code": "GATEWAY_ERROR",
                        "error_reason": "payment_timed_out",
                        "error_description": "Timeout",
                    }
                }
            },
        }

        norm_ev, risk_ev, rc = process_payment_failed_event(raw_webhook, in_memory_db)
        risk_id = risk_ev.risk_id

        # Context: Night time 23:30 (DND violation for customer-facing payment_link)
        night_ctx = GuardrailContext(current_time=datetime(2026, 8, 27, 23, 30, 0))

        res = start_recovery_workflow(
            conn=in_memory_db,
            risk_id=risk_id,
            context=night_ctx,
            simulated_action_outcomes={
                0: ExecutionStatusEnum.FAILED,
                1: ExecutionStatusEnum.SUCCESS,
            },
            customer_id="cust_audit_block",
        )
        assert res.final_status == EventStatus.ESCALATED

        audit_trail = get_audit_trail(in_memory_db, risk_id)
        decisions = [entry.decision for entry in audit_trail]

        expected_decisions = [
            "event_normalized",
            "revenue_at_risk_detected",
            "root_cause_identified",
            "action_selected",
            "guardrail_pass",
            "action_executed",
            "outcome_recorded",
            "action_selected",
            "guardrail_block",
            "escalated",
        ]

        assert decisions == expected_decisions

        # Verify executor actions in audit: exactly 1 execution (action 0). Action 1 was never executed!
        executor_audits = [e for e in audit_trail if e.layer == "action_executor"]
        assert len(executor_audits) == 1
        exec_payload = json.loads(executor_audits[0].output_json)
        assert exec_payload["action_type"] == "smart_retry"

    def test_phase6_done_when_criterion(self, in_memory_db):
        """
        Phase 6 "Done when" criterion:
        A single risk_id's full journey can be queried as an ordered list of rows.
        """
        raw_webhook = {
            "entity": "event",
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_phase6_done_001",
                        "amount": 2200000,
                        "currency": "INR",
                        "customer_id": "cust_p6_done",
                        "error_code": "GATEWAY_ERROR",
                        "error_reason": "payment_timed_out",
                        "error_description": "Timeout",
                    }
                }
            },
        }

        norm_ev, risk_ev, rc = process_payment_failed_event(raw_webhook, in_memory_db)
        risk_id = risk_ev.risk_id

        start_recovery_workflow(
            conn=in_memory_db,
            risk_id=risk_id,
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={0: ExecutionStatusEnum.SUCCESS},
            customer_id="cust_p6_done",
        )

        from src.reconciliation import reconcile_payment_status
        reconcile_payment_status(in_memory_db, risk_id, forced_status="RECOVERED")

        rows = get_audit_trail_for_risk(in_memory_db, risk_id)
        assert len(rows) >= 7
        # Verify strict ascending ordering of ID
        ids = [r.id for r in rows]
        assert ids == sorted(ids)
        assert rows[-1].decision == "payment_status_reconciled_recovered"
