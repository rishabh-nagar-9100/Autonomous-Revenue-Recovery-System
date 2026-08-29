import pytest
import sqlite3
import json
from unittest.mock import MagicMock, patch
from datetime import datetime
from src.models import (
    NormalizedEvent,
    RiskEvent,
    RootCauseEnum,
    ActionType,
    ExecutionStatusEnum,
    EventStatus,
    RiskType,
    Priority,
)
from src.db import init_db
from src.root_cause import diagnose_root_cause, diagnose_root_cause_rules
from src.llm import (
    diagnose_root_cause_llm,
    draft_action_message_llm,
    get_deterministic_message_fallback,
    LLMRootCauseResponse,
)
from src.decision_engine import next_action
from src.pipeline import process_payment_failed_event
from src.guardrails import GuardrailContext
from src.outcome_tracker import start_recovery_workflow


@pytest.fixture
def in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def create_mock_anthropic_client(response_text: str):
    """Helper to create a mock Anthropic client returning given text."""
    client = MagicMock()
    mock_block = MagicMock()
    mock_block.text = response_text
    mock_response = MagicMock()
    mock_response.content = [mock_block]
    client.messages.create.return_value = mock_response
    return client


class TestTieredRootCauseAndLLM:
    def test_case_a_known_error_code_does_not_call_llm(self):
        """Proof that a known deterministic error code never calls the LLM."""
        event = NormalizedEvent(
            event_id="pay_known_001",
            event_type="payment_failed",
            amount=5000.0,
            customer_id="cust_001",
            error_code="GATEWAY_ERROR",
            error_reason="payment_timed_out",
            error_description="Bank server timed out.",
        )
        risk_ev = RiskEvent(
            risk_id="risk_known_001",
            event_id="pay_known_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=5000.0,
            priority=Priority.MEDIUM,
            status=EventStatus.DETECTED,
        )

        mock_client = MagicMock()
        rc = diagnose_root_cause(event, risk_ev, use_llm_fallback=True, llm_client=mock_client)

        assert rc.root_cause == RootCauseEnum.BANK_TIMEOUT
        assert rc.source == "rule"
        assert rc.confidence == 1.0
        mock_client.messages.create.assert_not_called()

    def test_case_b_ambiguous_error_calls_llm_and_accepts_valid_enum(self):
        """Ambiguous signal calls LLM fallback and records source as llm."""
        event = NormalizedEvent(
            event_id="pay_ambiguous_001",
            event_type="payment_failed",
            amount=7500.0,
            customer_id="cust_002",
            error_code="CUSTOM_UNRECOGNIZED_CODE",
            error_reason="unmapped_exception",
            error_description="Customer account balance insufficient for clearing.",
        )
        risk_ev = RiskEvent(
            risk_id="risk_ambiguous_001",
            event_id="pay_ambiguous_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=7500.0,
            priority=Priority.MEDIUM,
            status=EventStatus.DETECTED,
        )

        mock_llm_json = json.dumps({
            "root_cause": "nsf",
            "confidence": 0.92,
            "reasoning": "Description states account balance insufficient for clearing."
        })
        mock_client = create_mock_anthropic_client(mock_llm_json)

        rc = diagnose_root_cause(event, risk_ev, use_llm_fallback=True, llm_client=mock_client)

        assert rc.root_cause == RootCauseEnum.NSF
        assert rc.source == "llm"
        assert rc.confidence == 0.92
        mock_client.messages.create.assert_called_once()

    def test_invalid_enum_from_llm_falls_back_safely(self):
        """LLM returning an unrecognized/hallucinated category falls back to unknown."""
        event = NormalizedEvent(
            event_id="pay_invalid_enum",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_003",
        )
        risk_ev = RiskEvent(
            risk_id="risk_invalid_enum",
            event_id="pay_invalid_enum",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.DETECTED,
        )

        mock_client = create_mock_anthropic_client('{"root_cause": "crypto_failure", "confidence": 0.8}')
        rc = diagnose_root_cause(event, risk_ev, use_llm_fallback=True, llm_client=mock_client)

        assert rc.root_cause == RootCauseEnum.UNKNOWN
        assert rc.source == "rule_fallback"
        assert rc.confidence == 0.0

    def test_malformed_json_from_llm_falls_back_safely(self):
        """LLM returning invalid JSON falls back without throwing."""
        event = NormalizedEvent(
            event_id="pay_malformed",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_004",
        )
        risk_ev = RiskEvent(
            risk_id="risk_malformed",
            event_id="pay_malformed",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.DETECTED,
        )

        mock_client = create_mock_anthropic_client("This is not JSON at all.")
        rc = diagnose_root_cause(event, risk_ev, use_llm_fallback=True, llm_client=mock_client)

        assert rc.root_cause == RootCauseEnum.UNKNOWN
        assert rc.source == "rule_fallback"

    def test_case_c_llm_exception_or_timeout_falls_back_safely(self):
        """Simulated API error/timeout falls back safely to unknown."""
        event = NormalizedEvent(
            event_id="pay_timeout",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_005",
        )
        risk_ev = RiskEvent(
            risk_id="risk_timeout",
            event_id="pay_timeout",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1000.0,
            priority=Priority.LOW,
            status=EventStatus.DETECTED,
        )

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = TimeoutError("Anthropic API request timed out after 3.0s")

        rc = diagnose_root_cause(event, risk_ev, use_llm_fallback=True, llm_client=mock_client)

        assert rc.root_cause == RootCauseEnum.UNKNOWN
        assert rc.source == "rule_fallback"
        assert rc.confidence == 0.0


class TestPlaybookProtectionAndMessageDrafting:
    def test_case_d_playbook_cannot_be_overridden_by_llm(self):
        """Deterministic PLAYBOOK remains authoritative regardless of any outside suggestion."""
        # For bank_timeout, index 0 is smart_retry, index 1 is payment_link, index 2 is None
        assert next_action(RootCauseEnum.BANK_TIMEOUT, 0) == ActionType.SMART_RETRY
        assert next_action(RootCauseEnum.BANK_TIMEOUT, 1) == ActionType.PAYMENT_LINK
        assert next_action(RootCauseEnum.BANK_TIMEOUT, 2) is None

        # Even for chronic_non_payer, index 0 is strictly None (immediate escalation)
        assert next_action(RootCauseEnum.CHRONIC_NON_PAYER, 0) is None

    def test_customer_facing_message_drafting_success(self):
        mock_client = create_mock_anthropic_client(
            "We noticed your payment of ₹12,500 was interrupted. Please complete your order securely using this link."
        )
        msg = draft_action_message_llm(
            risk_id="risk_msg_01",
            action_type=ActionType.PAYMENT_LINK,
            amount=12500.0,
            customer_id="cust_101",
            root_cause=RootCauseEnum.BANK_TIMEOUT,
            client=mock_client,
        )

        assert "12,500" in msg or "payment" in msg
        assert len(msg) > 10

    def test_customer_message_drafting_failure_uses_deterministic_template(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("Service unavailable")

        msg = draft_action_message_llm(
            risk_id="risk_msg_fail",
            action_type=ActionType.PAYMENT_LINK,
            amount=8000.0,
            customer_id="cust_102",
            root_cause=RootCauseEnum.EXPIRED_CARD,
            client=mock_client,
        )

        assert "₹8,000.00" in msg
        assert "secure link" in msg


class TestPhase8EndToEndScenarios:
    def test_end_to_end_pipeline_with_llm_diagnosed_root_cause(self, in_memory_db):
        """
        Complete end-to-end recovery journey where root cause is diagnosed via LLM fallback.
        """
        raw_event = {
            "entity": "event",
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_p8_llm_e2e",
                        "amount": 1600000,  # 16,000 INR
                        "currency": "INR",
                        "customer_id": "cust_p8_01",
                        "error_code": "MYSTERY_CODE",
                        "error_reason": "unknown_reason",
                        "error_description": "Network timeout occurred with partner gateway.",
                    }
                }
            },
        }

        mock_llm_json = json.dumps({
            "root_cause": "bank_timeout",
            "confidence": 0.95,
            "reasoning": "Description mentions partner gateway network timeout."
        })
        mock_client = create_mock_anthropic_client(mock_llm_json)

        # 1. Pipeline processing using LLM fallback
        norm_ev, risk_ev, rc = process_payment_failed_event(
            raw_event=raw_event,
            conn=in_memory_db,
            use_llm_fallback=True,
            llm_client=mock_client,
        )

        assert rc.root_cause == RootCauseEnum.BANK_TIMEOUT
        assert rc.source == "llm"

        # 2. Closed-loop recovery using the diagnosed root cause
        daytime_ctx = GuardrailContext(current_time=datetime(2026, 8, 27, 14, 0, 0))
        wf_res = start_recovery_workflow(
            conn=in_memory_db,
            risk_id=risk_ev.risk_id,
            context=daytime_ctx,
            simulated_action_outcomes={0: ExecutionStatusEnum.SUCCESS},
            customer_id="cust_p8_01",
        )

        assert wf_res.final_status == EventStatus.RECOVERED
        assert wf_res.amount_recovered == 16000.0
