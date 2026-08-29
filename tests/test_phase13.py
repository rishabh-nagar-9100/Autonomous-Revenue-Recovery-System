import os
import json
import sqlite3
import pytest
from datetime import datetime, timedelta
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
    InfoRequestStatusEnum,
)
from src.db import (
    init_db,
    insert_risk_event,
    insert_root_cause,
    get_risk_event,
    get_root_cause,
    get_outcomes_for_risk,
    get_escalation,
    get_executions_for_risk,
    get_info_request,
    get_audit_trail_for_risk,
)
from src.guardrails import GuardrailContext
from src.outcome_tracker import start_recovery_workflow
from src.info_gathering import (
    can_request_info,
    request_customer_info,
    parse_customer_response,
    check_recovery_eligibility,
    process_customer_info_response,
    handle_info_timeout,
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
    # 2:00 PM allowed hours
    return GuardrailContext(current_time=datetime(2026, 8, 29, 14, 0))


class TestPhase13InformationGathering:
    def test_parse_customer_response_strict_enum_mapping(self):
        """Requirement 6 & 7: Customer response mapped strictly to fixed RootCauseEnum or None."""
        assert parse_customer_response("card expire ho gaya hai") == RootCauseEnum.EXPIRED_CARD
        assert parse_customer_response("my card validity is over") == RootCauseEnum.EXPIRED_CARD
        assert parse_customer_response("low balance in bank account") == RootCauseEnum.NSF
        assert parse_customer_response("paise nahi hai account me") == RootCauseEnum.NSF
        assert parse_customer_response("bank server was down technical error") == RootCauseEnum.BANK_TIMEOUT
        assert parse_customer_response("forgot to pay overdue invoice") == RootCauseEnum.RECENT_OVERDUE

        # Gibberish / unsupported / invalid returns None (NEVER accepts free-form strings)
        assert parse_customer_response("asdfghjk 12345") is None
        assert parse_customer_response("random text nothing relevant") is None

    def test_second_clarification_attempt_blocked(self, memory_db, daytime_context):
        """Requirement E: Maximum exactly ONE clarification question per risk_id. Second attempt blocked."""
        risk_id = "risk_attempt_limit"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_limit",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            # First attempt -> allowed
            assert can_request_info(memory_db, risk_id) is True
            res1 = request_customer_info(memory_db, risk_id, amount=5000.0, customer_id="cust_1", context=daytime_context)
            assert res1["status"] == "requested"

            # Second attempt -> blocked!
            assert can_request_info(memory_db, risk_id) is False
            res2 = request_customer_info(memory_db, risk_id, amount=5000.0, customer_id="cust_1", context=daytime_context)
            assert res2["status"] == "blocked"
            assert res2["reason"] == "info_gathering_attempt_limit_exceeded"

    def test_no_money_action_while_waiting_for_customer_info(self, memory_db, daytime_context):
        """Requirement 4 & F: No payment/money action may execute while WAITING_FOR_CUSTOMER_INFO."""
        risk_id = "risk_no_money_action"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_no_money",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=6500.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            wf_res = start_recovery_workflow(memory_db, risk_id, context=daytime_context)

        assert wf_res.final_status == EventStatus.WAITING_FOR_CUSTOMER_INFO
        assert get_risk_event(memory_db, risk_id).status == EventStatus.WAITING_FOR_CUSTOMER_INFO

        # VERIFY ZERO EXECUTIONS IN DATABASE
        execs = get_executions_for_risk(memory_db, risk_id)
        assert len(execs) == 0

    def test_dnd_blocks_clarification(self, memory_db):
        """Requirement 5 & G: DND hours block clarification request and escalate safely."""
        risk_id = "risk_dnd_blocked"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_dnd",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        dnd_context = GuardrailContext(current_time=datetime(2026, 8, 29, 23, 30))  # 11:30 PM (DND)

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            res = request_customer_info(memory_db, risk_id, amount=4000.0, customer_id="cust_dnd", context=dnd_context)

        assert res["status"] == "guardrail_blocked"
        assert res["escalated"] is True
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

    def test_customer_opt_out_blocks_clarification(self, memory_db):
        """Requirement 5 & H: Customer opt-out blocks clarification request."""
        risk_id = "risk_optout_blocked"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_optout",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        optout_context = GuardrailContext(current_time=datetime(2026, 8, 29, 14, 0), customer_opted_out=True)

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            res = request_customer_info(memory_db, risk_id, amount=3000.0, customer_id="cust_optout", context=optout_context)

        assert res["status"] == "guardrail_blocked"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

    def test_feature_flag_disabled_no_clarification(self, memory_db, daytime_context):
        """Requirement 12 & I: INFO_GATHERING_ENABLED=false -> no clarification sent, escalates safely."""
        risk_id = "risk_flag_off"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_flag_off",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5500.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "false"}):
            wf_res = start_recovery_workflow(memory_db, risk_id, context=daytime_context)

        assert wf_res.final_status == EventStatus.ESCALATED
        assert get_info_request(memory_db, risk_id) is None

    def test_already_recovered_transaction_response_ignored(self, memory_db):
        """Requirement J: Already RECOVERED transaction ignores customer response and does not resume recovery."""
        risk_id = "risk_already_rec"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_rec",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=7000.0,
            priority=Priority.HIGH,
            status=EventStatus.RECOVERED,
        )
        insert_risk_event(memory_db, risk)

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            res = process_customer_info_response(memory_db, risk_id, response_text="card expire ho gaya hai")

        assert res["status"] == "ignored"
        assert res["reason"] == "already_recovered"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.RECOVERED


class TestPhase13CriticalTraces:
    def test_trace_a_unknown_clarification_supported_cause_recovery(self, memory_db, daytime_context):
        """
        TRACE A: UNKNOWN -> clarification sent -> customer: "card expire ho gaya" -> LLM extraction = expired_card -> eligibility PASS -> payment_link -> SUCCESS -> RECOVERED
        """
        risk_id = "risk_trace_a_info"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_a_info",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4200.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            # 1. Start recovery -> enters WAITING_FOR_CUSTOMER_INFO
            wf1 = start_recovery_workflow(memory_db, risk_id, context=daytime_context)
            assert wf1.final_status == EventStatus.WAITING_FOR_CUSTOMER_INFO
            assert get_risk_event(memory_db, risk_id).status == EventStatus.WAITING_FOR_CUSTOMER_INFO

            # 2. Customer responds with valid reason
            res_info = process_customer_info_response(memory_db, risk_id, response_text="card expire ho gaya hai")

        assert res_info["status"] == "resumed"
        assert res_info["extracted_root_cause"] == "expired_card"

        # 3. Verify root cause updated to expired_card
        rc = get_root_cause(memory_db, risk_id)
        assert rc.root_cause == RootCauseEnum.EXPIRED_CARD

        # 4. Verify risk event status is RECOVERED and outcome recorded
        assert get_risk_event(memory_db, risk_id).status == EventStatus.RECOVERED
        outcomes = get_outcomes_for_risk(memory_db, risk_id)
        assert len(outcomes) == 1
        assert outcomes[0].amount_recovered == 4200.0

    def test_trace_b_unknown_clarification_unusable_response_escalated(self, memory_db, daytime_context):
        """
        TRACE B: UNKNOWN -> clarification -> customer response unusable/gibberish -> ESCALATED
        """
        risk_id = "risk_trace_b_info"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_b_info",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=3800.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            start_recovery_workflow(memory_db, risk_id, context=daytime_context)
            res_info = process_customer_info_response(memory_db, risk_id, response_text="xyz123 random gibberish response")

        assert res_info["status"] == "escalated"
        assert res_info["reason"] == "unusable_info_response"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED
        assert "unusable_info_response" in get_escalation(memory_db, risk_id).reason

    def test_trace_c_unknown_clarification_timeout_escalated(self, memory_db, daytime_context):
        """
        TRACE C: UNKNOWN -> clarification -> no response -> timeout -> ESCALATED
        """
        risk_id = "risk_trace_c_info"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_c_info",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=2900.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            start_recovery_workflow(memory_db, risk_id, context=daytime_context)
            res_timeout = handle_info_timeout(memory_db, risk_id)

        assert res_timeout["status"] == "escalated"
        assert res_timeout["reason"] == "info_request_timeout"
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED
        assert get_info_request(memory_db, risk_id).status == InfoRequestStatusEnum.TIMED_OUT

    def test_trace_d_unknown_clarification_recovery_eligibility_expired_escalated(self, memory_db, daytime_context):
        """
        TRACE D: UNKNOWN -> clarification -> supported cause -> recovery eligibility expired (>7 days) -> ESCALATED -> NO payment action executed
        """
        risk_id = "risk_trace_d_info"
        # Created 10 days ago (window is 7 days)
        old_date = datetime.utcnow() - timedelta(days=10)
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_d_info",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=8500.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
            created_at=old_date,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            start_recovery_workflow(memory_db, risk_id, context=daytime_context)
            res_info = process_customer_info_response(memory_db, risk_id, response_text="card expire ho gaya hai")

        assert res_info["status"] == "escalated"
        assert "recovery_window_expired" in res_info["reason"]
        assert get_risk_event(memory_db, risk_id).status == EventStatus.ESCALATED

        # CRITICAL VERIFICATION: NO PAYMENT ACTION EXECUTED!
        execs = get_executions_for_risk(memory_db, risk_id)
        assert len(execs) == 0

    def test_trace_e_attempted_second_clarification_blocked(self, memory_db, daytime_context):
        """
        TRACE E: UNKNOWN -> attempted second clarification -> blocked by attempt limit (max 1)
        """
        risk_id = "risk_trace_e_info"
        risk = RiskEvent(
            risk_id=risk_id,
            event_id="evt_trace_e_info",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=4800.0,
            priority=Priority.HIGH,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)
        insert_root_cause(memory_db, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.UNKNOWN, confidence=0.0))

        with patch.dict(os.environ, {"INFO_GATHERING_ENABLED": "true"}):
            # Clarification 1
            request_customer_info(memory_db, risk_id, amount=4800.0, customer_id="cust_e", context=daytime_context)

            # Attempt clarification 2 -> blocked
            res2 = request_customer_info(memory_db, risk_id, amount=4800.0, customer_id="cust_e", context=daytime_context)

        assert res2["status"] == "blocked"
        assert res2["reason"] == "info_gathering_attempt_limit_exceeded"
