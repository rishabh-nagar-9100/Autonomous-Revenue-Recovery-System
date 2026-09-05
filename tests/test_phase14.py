import os
import json
import sqlite3
import pytest
from datetime import datetime
from unittest.mock import patch

from src.models import (
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
    RootCause,
    RootCauseEnum,
    ActionType,
    ExecutionStatusEnum,
    VoiceIntent,
)
from src.db import (
    init_db,
    insert_risk_event,
    insert_root_cause,
    get_risk_event,
    get_outcomes_for_risk,
    get_escalation,
    get_executions_for_risk,
    list_voice_interactions_for_risk,
    get_audit_trail_for_risk,
)
from src.guardrails import GuardrailContext
from src.voice import (
    MockSTTAdapter,
    MockTTSAdapter,
    check_voice_eligibility,
    extract_hinglish_intent,
    process_voice_interaction,
    initiate_outbound_voice_call,
)


@pytest.fixture
def memory_db():
    conn = sqlite3.Connection(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def daytime_context():
    # 2:00 PM allowed daytime hours
    return GuardrailContext(current_time=datetime(2026, 8, 29, 14, 0))


class TestPhase14VoiceRecovery:
    def test_voice_feature_disabled_endpoint_blocked(self, memory_db):
        """Test 1 & 20: VOICE_ENABLED=false gates voice interactions and endpoints."""
        risk_id = "risk_voice_off"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_off",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2500.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "false"}):
            res_call = initiate_outbound_voice_call(memory_db, risk_id, "+919876543210")
            assert res_call["status"] == "blocked"
            assert res_call["reason"] == "voice_disabled"

            res_int = process_voice_interaction(memory_db, risk_id, "Payment link bhej do")
            assert res_int["status"] == "blocked"
            assert res_int["reason"] == "voice_disabled"

    def test_eligible_customer_call_initiation_permitted(self, memory_db, daytime_context):
        """Test 2: Eligible customer initiates outbound call successfully."""
        risk_id = "risk_voice_eligible"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_elig",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3200.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = initiate_outbound_voice_call(memory_db, risk_id, "+919876543210", context=daytime_context)

        assert res["status"] == "call_initiated"
        assert "call_sid" in res
        interactions = list_voice_interactions_for_risk(memory_db, risk_id)
        assert len(interactions) == 1
        assert interactions[0].eligibility_status == "ELIGIBLE"

    def test_opted_out_customer_call_blocked(self, memory_db, daytime_context):
        """Test 3: Customer opt-out blocks call initiation."""
        risk_id = "risk_voice_optout"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_optout",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        optout_ctx = GuardrailContext(current_time=datetime(2026, 8, 29, 14, 0), customer_opted_out=True)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = initiate_outbound_voice_call(memory_db, risk_id, "+919876543210", context=optout_ctx)

        assert res["status"] == "blocked"
        assert res["reason"] == "customer_opted_out"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

    def test_dnd_hours_call_blocked(self, memory_db):
        """Test 4: DND hours (11:30 PM) block voice interaction and escalate."""
        risk_id = "risk_voice_dnd"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_dnd",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3500.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        dnd_ctx = GuardrailContext(current_time=datetime(2026, 8, 29, 23, 30))

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = initiate_outbound_voice_call(memory_db, risk_id, "+919876543210", context=dnd_ctx)

        assert res["status"] == "blocked"
        assert res["reason"] == "dnd_hours"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

    def test_invalid_phone_number_call_blocked(self, memory_db, daytime_context):
        """Test 5: Invalid phone number blocks call initiation."""
        risk_id = "risk_voice_invalid_phone"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_phone",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2800.0,
            priority=Priority.LOW,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = initiate_outbound_voice_call(memory_db, risk_id, "123", context=daytime_context)

        assert res["status"] == "blocked"
        assert res["reason"] == "invalid_phone_number"

    def test_expired_recovery_call_blocked(self, memory_db, daytime_context):
        """Test 6: Already RECOVERED transaction blocks voice call."""
        risk_id = "risk_voice_recovered"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_rec",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.HIGH,
            status=EventStatus.RECOVERED,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = initiate_outbound_voice_call(memory_db, risk_id, "+919876543210", context=daytime_context)

        assert res["status"] == "blocked"
        assert "invalid_status" in res["reason"]

    def test_mock_stt_adapter_works(self):
        """Test 7: MockSTTAdapter transcribes clean text string."""
        stt = MockSTTAdapter()
        assert stt.transcribe("  Payment link bhej do  ") == "Payment link bhej do"

    def test_hinglish_intent_classification(self):
        """Test 8, 9, 10, 11, 12: Hinglish intent extraction into fixed VoiceIntent enums."""
        assert extract_hinglish_intent("Payment link bhej do please") == VoiceIntent.SEND_PAYMENT_LINK
        assert extract_hinglish_intent("bhej do link sms pe") == VoiceIntent.SEND_PAYMENT_LINK
        assert extract_hinglish_intent("Haan main payment kar diya") == VoiceIntent.CONFIRM_PAYMENT
        assert extract_hinglish_intent("Payment ka status kya hai?") == VoiceIntent.ASK_STATUS
        assert extract_hinglish_intent("Mujhe human agent se baat karni hai") == VoiceIntent.SPEAK_TO_HUMAN
        assert extract_hinglish_intent("Nahi abhi nahi chahiye cancel kar do") == VoiceIntent.DECLINE

    def test_unsupported_intent_human_handoff(self, memory_db, daytime_context):
        """Test 13: Unsupported intent defaults to SPEAK_TO_HUMAN and escalates safely."""
        risk_id = "risk_voice_unsupported"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_unsupported",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3600.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = process_voice_interaction(memory_db, risk_id, "qwerty random unsupported transcript", context=daytime_context)

        assert res["status"] == "escalated_to_human"
        assert res["intent"] == "SPEAK_TO_HUMAN"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

    def test_voice_payment_link_request_existing_guardrails_execute(self, memory_db, daytime_context):
        """Test 14, 17, 18, 19: Voice payment_link routes through existing guardrails, executor, and cannot alter amount/recipient."""
        risk_id = "risk_voice_guardrail_exec"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_gexec",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4500.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = process_voice_interaction(memory_db, risk_id, "Payment link bhej do", context=daytime_context)

        assert res["status"] == "executed"
        assert res["intent"] == "SEND_PAYMENT_LINK"
        assert res["guardrail_result"] == "PASS"
        assert res["execution_result"] == "SUCCESS"

        # VERIFY AMOUNT AND RECIPIENT REMAIN UNTOUCHED (FROM RISK EVENT)
        execs = get_executions_for_risk(memory_db, risk_id)
        assert len(execs) == 1
        assert execs[0].action_type == ActionType.PAYMENT_LINK
        assert get_risk_event(memory_db, risk_id).status == EventStatus.IN_PROGRESS
        from src.reconciliation import reconcile_payment_status
        reconcile_payment_status(memory_db, risk_id, forced_status="RECOVERED")
        assert get_risk_event(memory_db, risk_id).status == EventStatus.RECOVERED

    def test_guardrail_block_voice_action_not_executed(self, memory_db, daytime_context):
        """Test 15: When guardrails BLOCK (e.g. amount > 50,000 threshold), voice action is NOT executed."""
        risk_id = "risk_voice_blocked_amount"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_high_amt",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=75000.0,  # Above human approval threshold 50k
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = process_voice_interaction(memory_db, risk_id, "Payment link bhej do", context=daytime_context)

        assert res["status"] == "guardrail_blocked"
        assert res["guardrail_result"] == "BLOCK"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

        # CRITICAL SAFETY: 0 EXECUTIONS IN DATABASE!
        execs = get_executions_for_risk(memory_db, risk_id)
        assert len(execs) == 0

    def test_voice_interaction_appears_in_audit_trail(self, memory_db, daytime_context):
        """Test 16: Voice interaction produces structured audit log trail."""
        risk_id = "risk_voice_audit"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_v_audit",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2900.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            process_voice_interaction(memory_db, risk_id, "Payment link bhej do", context=daytime_context)

        audit_entries = get_audit_trail_for_risk(memory_db, risk_id)
        voice_audits = [a for a in audit_entries if a.layer == "voice_engine"]
        assert len(voice_audits) >= 1
        assert "SEND_PAYMENT_LINK" in voice_audits[0].input_json


class TestPhase14CriticalTraces:
    def test_trace_a_voice_to_recovery(self, memory_db, daytime_context):
        """
        TRACE A: customer speaks Hinglish -> eligibility PASS -> STT -> intent = SEND_PAYMENT_LINK -> existing playbook/action -> guardrail PASS -> payment_link execution -> audit
        """
        risk_id = "risk_trace_a_voice"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_a_voice",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=6200.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            # Outbound call initiation
            call_res = initiate_outbound_voice_call(memory_db, risk_id, "+919876543210", context=daytime_context)
            assert call_res["status"] == "call_initiated"

            # Voice interaction: "Payment link bhej do"
            res = process_voice_interaction(memory_db, risk_id, "Payment link bhej do", context=daytime_context)

        assert res["status"] == "executed"
        assert res["intent"] == "SEND_PAYMENT_LINK"
        assert res["action_requested"] == "payment_link"
        assert res["guardrail_result"] == "PASS"
        assert res["execution_result"] == "SUCCESS"

        # Database verification
        assert get_risk_event(memory_db, risk_id).status == EventStatus.IN_PROGRESS
        from src.reconciliation import reconcile_payment_status
        reconcile_payment_status(memory_db, risk_id, forced_status="RECOVERED")
        assert get_risk_event(memory_db, risk_id).status == EventStatus.RECOVERED
        outcomes = get_outcomes_for_risk(memory_db, risk_id)
        assert outcomes[0].amount_recovered == 6200.0

    def test_trace_b_voice_safety_block(self, memory_db, daytime_context):
        """
        TRACE B: customer speaks -> eligibility PASS -> intent = SEND_PAYMENT_LINK -> guardrail BLOCK -> payment action NOT executed -> escalation/audit
        """
        risk_id = "risk_trace_b_voice"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_b_voice",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=85000.0,  # Exceeds human approval threshold 50,000
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = process_voice_interaction(memory_db, risk_id, "Payment link bhej do", context=daytime_context)

        assert res["status"] == "guardrail_blocked"
        assert res["guardrail_result"] == "BLOCK"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

        # NO PAYMENT ACTION EXECUTED!
        execs = get_executions_for_risk(memory_db, risk_id)
        assert len(execs) == 0

    def test_trace_c_opted_out_eligibility_block(self, memory_db, daytime_context):
        """
        TRACE C: customer opted-out -> eligibility BLOCK -> no call initiated -> reason audited
        """
        risk_id = "risk_trace_c_voice"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_c_voice",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4800.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        optout_ctx = GuardrailContext(current_time=datetime(2026, 8, 29, 14, 0), customer_opted_out=True)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = initiate_outbound_voice_call(memory_db, risk_id, "+919876543210", context=optout_ctx)

        assert res["status"] == "blocked"
        assert res["reason"] == "customer_opted_out"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

        # Audit trail verification
        audit_entries = get_audit_trail_for_risk(memory_db, risk_id)
        assert any(a.decision == "voice_call_blocked_escalated" for a in audit_entries)

    def test_trace_d_human_handoff(self, memory_db, daytime_context):
        """
        TRACE D: customer: "agent se baat karni hai" -> SPEAK_TO_HUMAN -> escalation -> audit -> no financial action
        """
        risk_id = "risk_trace_d_voice"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_d_voice",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3900.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"VOICE_ENABLED": "true"}):
            res = process_voice_interaction(memory_db, risk_id, "Mujhe human agent se baat karni hai", context=daytime_context)

        assert res["status"] == "escalated_to_human"
        assert res["intent"] == "SPEAK_TO_HUMAN"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED
        assert get_escalation(memory_db, risk_id).reason == "voice_intent:speak_to_human"

        # NO FINANCIAL ACTION EXECUTED!
        execs = get_executions_for_risk(memory_db, risk_id)
        assert len(execs) == 0
