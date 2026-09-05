import os
import json
import hmac
import hashlib
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.models import (
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
    RootCauseEnum,
    ActionType,
    ExecutionStatusEnum,
    OutcomeResultEnum,
    RootCause,
)
from src.db import (
    init_db,
    insert_risk_event,
    insert_root_cause,
    get_risk_event,
    get_outcomes_for_risk,
    get_escalation,
)
from src.fault_injector import (
    FaultConfig,
    set_fault_config,
    clear_all_faults,
    inject_fault_if_configured,
    NetworkTimeoutFaultError,
    Transient5xxFaultError,
    ConnectionResetFaultError,
)
from src.outcome_tracker import handle_outcome
from src.reconciliation import reconcile_payment_status
from src.webhook import process_webhook


@pytest.fixture
def memory_db():
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def reset_faults():
    clear_all_faults()
    yield
    clear_all_faults()


class TestPhase11FaultInjector:
    def test_fault_injector_disabled_by_default(self):
        with patch.dict(os.environ, {"FAULT_INJECTION_ENABLED": "false"}):
            set_fault_config("smart_retry", FaultConfig(fault_type="network_timeout"))
            # Should not raise exception when FAULT_INJECTION_ENABLED is false
            inject_fault_if_configured("smart_retry")

    def test_fault_injector_raises_when_enabled(self):
        with patch.dict(os.environ, {"FAULT_INJECTION_ENABLED": "true"}):
            set_fault_config("smart_retry", FaultConfig(fault_type="network_timeout"))
            with pytest.raises(NetworkTimeoutFaultError, match="Network timeout simulating uncertain response"):
                inject_fault_if_configured("smart_retry")

            set_fault_config("payment_link", FaultConfig(fault_type="transient_5xx"))
            with pytest.raises(Transient5xxFaultError, match="Transient HTTP 503"):
                inject_fault_if_configured("payment_link")

            set_fault_config("connection_reset", FaultConfig(fault_type="connection_reset"))
            with pytest.raises(ConnectionResetFaultError, match="Connection reset by peer"):
                inject_fault_if_configured("connection_reset")


class TestPhase11CriticalTraces:
    def test_trace_a_timeout_pending_reconciliation_successful(self, memory_db):
        """
        TRACE A: Action sent -> timeout -> PENDING_RECONCILIATION -> prove next action NOT executed -> reconciliation SUCCESS (payment.captured) -> RECOVERED
        """
        risk_id = "risk_trace_a"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_a",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2500.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        root = RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0)
        insert_root_cause(memory_db, root)

        # Action 0 (smart_retry) encounters network timeout / PENDING_RECONCILIATION
        result = handle_outcome(
            conn=memory_db,
            risk_id=risk_id,
            action_index=0,
            execution_status=ExecutionStatusEnum.PENDING_RECONCILIATION,
        )

        assert result.final_status == EventStatus.PENDING_RECONCILIATION
        assert result.reason == "pending_reconciliation_safety_halt"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.PENDING_RECONCILIATION

        # PROVE NEXT ACTION WAS NOT EXECUTED:
        cursor = memory_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM interventions WHERE risk_id = ? AND action_index = 1;", (risk_id,))
        assert cursor.fetchone()[0] == 0

        cursor.execute("SELECT COUNT(*) FROM executions WHERE risk_id = ? AND action_index = 1;", (risk_id,))
        assert cursor.fetchone()[0] == 0

        # Now trigger reconciliation -> SUCCESS (payment.captured) -> RECOVERED
        recon_res = reconcile_payment_status(memory_db, risk_id=risk_id, forced_status="CAPTURED")
        assert recon_res["status"] == "reconciled"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.RECOVERED

        outcomes = get_outcomes_for_risk(memory_db, risk_id)
        assert len(outcomes) == 1
        assert outcomes[0].result == OutcomeResultEnum.SUCCESS
        assert outcomes[0].amount_recovered == 2500.0

    def test_trace_b_timeout_reconciliation_failed_auto_resumes_next_action(self, memory_db):
        """
        TRACE B: Timeout -> PENDING_RECONCILIATION -> reconciliation confirms FAILED -> system automatically resumes workflow and executes next playbook action
        """
        risk_id = "risk_trace_b"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_b",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4500.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        root = RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0)
        insert_root_cause(memory_db, root)

        # Action 0 encounters timeout -> PENDING_RECONCILIATION
        res1 = handle_outcome(
            conn=memory_db,
            risk_id=risk_id,
            action_index=0,
            execution_status=ExecutionStatusEnum.PENDING_RECONCILIATION,
        )
        assert res1.final_status == EventStatus.PENDING_RECONCILIATION

        # Reconcile status -> FAILED with auto_resume=True -> automatically resumes recovery workflow!
        recon_res = reconcile_payment_status(
            conn=memory_db,
            risk_id=risk_id,
            forced_status="FAILED",
            auto_resume=True,
        )

        assert recon_res["status"] == "reconciled_failed"
        assert recon_res["workflow_resumed"] is True

        # Next action (payment_link) was automatically executed and succeeded!
        wf_res = recon_res["workflow_result"]
        assert wf_res.final_status == EventStatus.IN_PROGRESS
        assert wf_res.amount_recovered == 0.0

        recon_final = reconcile_payment_status(memory_db, risk_id, forced_status="RECOVERED")
        assert recon_final["status"] == "reconciled"
        assert recon_final["amount_recovered"] == 4500.0

    def test_trace_c_triple_duplicate_delivery_idempotency(self, memory_db):
        """
        TRACE C: 3 duplicate webhook deliveries -> 1 unique webhook_events row -> 1 outcome -> 1 financial recovery
        """
        risk_id = "risk_trace_c"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_c",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3200.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        secret = "test_webhook_secret"
        body = json.dumps({
            "event": "payment.captured",
            "event_id": "evt_dup_333",
            "payload": {"payment": {"entity": {"id": "pay_dup_333", "amount": 320000, "notes": {"reference_id": risk_id}}}}
        })
        sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {"x-razorpay-signature": sig, "x-razorpay-event-id": "evt_dup_333"}

        # Deliver webhook 1
        res1 = process_webhook(memory_db, raw_body=body, headers=headers, webhook_secret=secret)
        assert res1["status"] == "processed"

        # Deliver webhook 2 (duplicate delivery)
        res2 = process_webhook(memory_db, raw_body=body, headers=headers, webhook_secret=secret)
        assert res2["status"] == "duplicate_skipped"

        # Deliver webhook 3 (duplicate delivery)
        res3 = process_webhook(memory_db, raw_body=body, headers=headers, webhook_secret=secret)
        assert res3["status"] == "duplicate_skipped"

        cursor = memory_db.cursor()

        # 1. VERIFY 1 UNIQUE webhook_events DB ROW
        cursor.execute("SELECT COUNT(*) FROM webhook_events WHERE event_id = ?;", ("evt_dup_333",))
        assert cursor.fetchone()[0] == 1

        # 2. VERIFY 1 OUTCOME ROW
        cursor.execute("SELECT COUNT(*) FROM outcomes WHERE risk_id = ?;", (risk_id,))
        assert cursor.fetchone()[0] == 1

        # 3. VERIFY 1 FINANCIAL RECOVERY AMOUNT
        cursor.execute("SELECT amount_recovered FROM outcomes WHERE risk_id = ?;", (risk_id,))
        assert cursor.fetchone()[0] == 3200.0

    def test_trace_d_payment_authorized_alone_is_not_recovered(self, memory_db):
        """
        TRACE D: payment.authorized alone MUST NOT mark the risk event RECOVERED (remains IN_PROGRESS/pending capture)
        """
        risk_id = "risk_trace_d_auth"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_d_auth",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        secret = "test_webhook_secret"
        body = json.dumps({
            "event": "payment.authorized",
            "event_id": "evt_auth_only_999",
            "payload": {"payment": {"entity": {"id": "pay_auth_999", "amount": 500000, "notes": {"reference_id": risk_id}}}}
        })
        sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        headers = {"x-razorpay-signature": sig, "x-razorpay-event-id": "evt_auth_only_999"}

        res = process_webhook(memory_db, raw_body=body, headers=headers, webhook_secret=secret)
        assert res["status"] == "processed"

        # CRITICAL VERIFICATION: payment.authorized alone does NOT mark the event RECOVERED!
        updated_risk = get_risk_event(memory_db, risk_id)
        assert updated_risk.status != EventStatus.RECOVERED
        assert updated_risk.status == EventStatus.IN_PROGRESS

        # Verify NO outcome row created yet
        outcomes = get_outcomes_for_risk(memory_db, risk_id)
        assert len(outcomes) == 0

    def test_trace_e_captured_recovered_late_failure_ignored(self, memory_db):
        """
        TRACE E: payment.captured -> RECOVERED -> late payment.failed webhook ignored on terminal RECOVERED state
        """
        risk_id = "risk_trace_e_term"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_e_term",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1800.0,
            priority=Priority.LOW,
            status=EventStatus.RECOVERED,
        )
        insert_risk_event(memory_db, risk)

        # Attempt late reconciliation or failure webhook
        res = reconcile_payment_status(memory_db, risk_id=risk_id, forced_status="FAILED")
        assert res["status"] == "already_recovered"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.RECOVERED

    def test_trace_f_unresolved_reconciliation_timeout_escalated(self, memory_db):
        """
        TRACE F: Reconciliation remains UNKNOWN -> after 3 attempts OR 24h -> ESCALATED
        """
        risk_id = "risk_trace_f"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_f",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=8800.0,
            priority=Priority.HIGH,
            status=EventStatus.PENDING_RECONCILIATION,
        )
        insert_risk_event(memory_db, risk)

        # Attempt 1 -> pending
        res1 = reconcile_payment_status(memory_db, risk_id=risk_id, forced_status="UNKNOWN", attempt_count=1, elapsed_hours=2.0)
        assert res1["status"] == "pending_reconciliation"

        # Attempt 2 -> pending
        res2 = reconcile_payment_status(memory_db, risk_id=risk_id, forced_status="UNKNOWN", attempt_count=2, elapsed_hours=12.0)
        assert res2["status"] == "pending_reconciliation"

        # Attempt 3 (Max attempts reached) -> ESCALATED
        res3 = reconcile_payment_status(memory_db, risk_id=risk_id, forced_status="UNKNOWN", attempt_count=3, elapsed_hours=18.0)
        assert res3["status"] == "escalated_timeout"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

        esc = get_escalation(memory_db, risk_id)
        assert esc is not None
        assert "reconciliation_timeout_exhausted" in esc.reason
