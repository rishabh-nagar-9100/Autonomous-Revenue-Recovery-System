import pytest
import sqlite3
from datetime import datetime
from src.models import (
    RiskType,
    Priority,
    EventStatus,
    RootCauseEnum,
    NormalizedEvent,
    RiskEvent,
    RootCause,
)
from src.db import (
    get_db_connection,
    init_db,
    insert_risk_event,
    insert_root_cause,
    get_risk_event,
    get_root_cause,
)
from src.ingestion import normalize_payment_failed_event
from src.risk_detector import detect_revenue_risk
from src.root_cause import diagnose_root_cause_rules
from src.pipeline import process_payment_failed_event


@pytest.fixture
def in_memory_db():
    """Provides an initialized in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestIngestionAndNormalization:
    def test_normalize_razorpay_webhook_payload(self):
        webhook_payload = {
            "entity": "event",
            "account_id": "acc_123456",
            "event": "payment.failed",
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_K1jL9mOpQrStUv",
                        "entity": "payment",
                        "amount": 1500000,  # 15,000 INR in paise
                        "currency": "INR",
                        "status": "failed",
                        "order_id": "order_K1jL234",
                        "invoice_id": None,
                        "international": False,
                        "method": "netbanking",
                        "amount_refunded": 0,
                        "refund_status": None,
                        "captured": False,
                        "description": "Subscription Renewal",
                        "card_id": None,
                        "bank": "HDFC",
                        "wallet": None,
                        "vpa": None,
                        "email": "customer@example.com",
                        "contact": "+919876543210",
                        "customer_id": "cust_888999",
                        "notes": {"plan": "enterprise_annual"},
                        "fee": None,
                        "tax": None,
                        "error_code": "GATEWAY_ERROR",
                        "error_description": "Payment was declined by the bank due to a timeout.",
                        "error_source": "gateway",
                        "error_step": "payment_authentication",
                        "error_reason": "payment_timed_out",
                        "created_at": 1724749200,
                    }
                }
            },
            "created_at": 1724749200,
        }

        normalized = normalize_payment_failed_event(webhook_payload)

        assert normalized.event_id == "pay_K1jL9mOpQrStUv"
        assert normalized.event_type == "payment_failed"
        assert normalized.amount == 15000.0  # Converted from 1500000 paise
        assert normalized.currency == "INR"
        assert normalized.customer_id == "cust_888999"
        assert normalized.error_code == "GATEWAY_ERROR"
        assert normalized.error_reason == "payment_timed_out"
        assert normalized.error_description == "Payment was declined by the bank due to a timeout."
        assert normalized.metadata.get("bank") == "HDFC"
        assert isinstance(normalized.timestamp, datetime)

    def test_normalize_direct_payload(self):
        direct_payload = {
            "event_id": "pay_direct_1001",
            "event_type": "payment_failed",
            "amount": 3499.50,
            "currency": "INR",
            "customer_id": "cust_direct_01",
            "error_code": "INSUFFICIENT_FUNDS",
            "error_reason": "insufficient_funds",
            "error_description": "Customer has insufficient funds in account",
            "metadata": {"retry_count": 0},
        }

        normalized = normalize_payment_failed_event(direct_payload)

        assert normalized.event_id == "pay_direct_1001"
        assert normalized.event_type == "payment_failed"
        assert normalized.amount == 3499.50
        assert normalized.customer_id == "cust_direct_01"
        assert normalized.error_reason == "insufficient_funds"
        assert normalized.metadata == {"retry_count": 0}

    def test_malformed_payload_raises_value_error(self):
        with pytest.raises(ValueError, match="Event payload must be a dictionary"):
            normalize_payment_failed_event(["invalid_payload"])

        with pytest.raises(ValueError, match="missing 'event_id' or 'id'"):
            normalize_payment_failed_event({"amount": 500.0})

        with pytest.raises(ValueError, match="missing 'amount'"):
            normalize_payment_failed_event({"event_id": "pay_no_amount"})

        with pytest.raises(ValueError, match="Invalid amount format"):
            normalize_payment_failed_event({"event_id": "pay_bad_amount", "amount": "not_a_number"})


class TestRevenueRiskDetector:
    def test_high_priority_for_large_amounts(self):
        event = NormalizedEvent(
            event_id="pay_high_01",
            event_type="payment_failed",
            amount=12000.0,
            customer_id="cust_01",
        )
        risk = detect_revenue_risk(event)

        assert risk.risk_id == "risk_pay_high_01"
        assert risk.event_id == "pay_high_01"
        assert risk.risk_type == RiskType.PAYMENT_FAILED
        assert risk.amount == 12000.0
        assert risk.priority == Priority.HIGH
        assert risk.status == EventStatus.DETECTED

    def test_high_priority_for_vip_metadata(self):
        event = NormalizedEvent(
            event_id="pay_vip_01",
            event_type="payment_failed",
            amount=1500.0,
            customer_id="cust_vip",
            metadata={"is_vip": True},
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == Priority.HIGH

    def test_medium_priority(self):
        event = NormalizedEvent(
            event_id="pay_med_01",
            event_type="payment_failed",
            amount=4500.0,
            customer_id="cust_02",
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == Priority.MEDIUM

    def test_low_priority(self):
        event = NormalizedEvent(
            event_id="pay_low_01",
            event_type="payment_failed",
            amount=899.0,
            customer_id="cust_03",
        )
        risk = detect_revenue_risk(event)
        assert risk.priority == Priority.LOW


class TestRootCauseEngine:
    def test_bank_timeout_mapping(self):
        event = NormalizedEvent(
            event_id="pay_bt_01",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_bt",
            error_code="GATEWAY_ERROR",
            error_reason="payment_timed_out",
        )
        risk = detect_revenue_risk(event)
        rc = diagnose_root_cause_rules(event, risk)

        assert rc.risk_id == "risk_pay_bt_01"
        assert rc.root_cause == RootCauseEnum.BANK_TIMEOUT
        assert rc.confidence == 1.0
        assert rc.source == "rule"

    def test_nsf_mapping(self):
        event = NormalizedEvent(
            event_id="pay_nsf_01",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_nsf",
            error_code="BAD_REQUEST_PAYMENT_FAILED_DUE_TO_INSUFFICIENT_FUNDS",
            error_reason="insufficient_funds",
        )
        risk = detect_revenue_risk(event)
        rc = diagnose_root_cause_rules(event, risk)

        assert rc.root_cause == RootCauseEnum.NSF
        assert rc.confidence == 1.0
        assert rc.source == "rule"

    def test_expired_card_mapping(self):
        event = NormalizedEvent(
            event_id="pay_exp_01",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_exp",
            error_code="CARD_EXPIRED",
            error_reason="card_expired",
        )
        risk = detect_revenue_risk(event)
        rc = diagnose_root_cause_rules(event, risk)

        assert rc.root_cause == RootCauseEnum.EXPIRED_CARD
        assert rc.confidence == 1.0
        assert rc.source == "rule"

    def test_chronic_non_payer_mapping(self):
        event = NormalizedEvent(
            event_id="pay_chronic_01",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_chronic",
            error_reason="payment_timed_out",
            metadata={"consecutive_failures": 5},
        )
        risk = detect_revenue_risk(event)
        rc = diagnose_root_cause_rules(event, risk)

        # Chronic non-payer rule overrides error reason
        assert rc.root_cause == RootCauseEnum.CHRONIC_NON_PAYER
        assert rc.confidence == 1.0
        assert rc.source == "rule"

    def test_unmapped_error_maps_to_unknown(self):
        event = NormalizedEvent(
            event_id="pay_unknown_01",
            event_type="payment_failed",
            amount=1000.0,
            customer_id="cust_unknown",
            error_code="SOME_UNRECOGNIZED_CODE",
            error_reason="unrecognized_custom_reason",
            error_description="custom gateway message",
        )
        risk = detect_revenue_risk(event)
        rc = diagnose_root_cause_rules(event, risk)

        assert rc.root_cause == RootCauseEnum.UNKNOWN
        assert rc.confidence == 0.0
        assert rc.source == "rule"


class TestPhase1DatabaseAndDoneCriteria:
    def test_sqlite_insert_and_retrieve_risk_event(self, in_memory_db):
        risk = RiskEvent(
            risk_id="risk_test_100",
            event_id="pay_test_100",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=7500.0,
            priority=Priority.MEDIUM,
            status=EventStatus.DETECTED,
            created_at=datetime(2026, 8, 27, 10, 30, 0),
        )
        insert_risk_event(in_memory_db, risk)
        retrieved = get_risk_event(in_memory_db, "risk_test_100")

        assert retrieved is not None
        assert retrieved.risk_id == "risk_test_100"
        assert retrieved.event_id == "pay_test_100"
        assert retrieved.risk_type == RiskType.PAYMENT_FAILED
        assert retrieved.amount == 7500.0
        assert retrieved.priority == Priority.MEDIUM
        assert retrieved.status == EventStatus.DETECTED
        assert retrieved.created_at == datetime(2026, 8, 27, 10, 30, 0)

    def test_sqlite_insert_and_retrieve_root_cause(self, in_memory_db):
        rc = RootCause(
            risk_id="risk_test_100",
            root_cause=RootCauseEnum.BANK_TIMEOUT,
            confidence=1.0,
            source="rule",
            created_at=datetime(2026, 8, 27, 10, 30, 0),
        )
        insert_root_cause(in_memory_db, rc)
        retrieved = get_root_cause(in_memory_db, "risk_test_100")

        assert retrieved is not None
        assert retrieved.risk_id == "risk_test_100"
        assert retrieved.root_cause == RootCauseEnum.BANK_TIMEOUT
        assert retrieved.confidence == 1.0
        assert retrieved.source == "rule"
        assert retrieved.created_at == datetime(2026, 8, 27, 10, 30, 0)

    def test_phase1_end_to_end_done_when_criterion(self, in_memory_db):
        """
        Phase 1 "Done when" criterion:
        One synthetic payment_failed event produces a correct risk_event + root_cause row in SQLite.
        """
        synthetic_webhook = {
            "entity": "event",
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_synthetic_phase1_001",
                        "amount": 2500000,  # 25,000 INR
                        "currency": "INR",
                        "status": "failed",
                        "customer_id": "cust_phase1_corp",
                        "error_code": "GATEWAY_ERROR",
                        "error_description": "Bank network timeout during payment authentication.",
                        "error_source": "gateway",
                        "error_reason": "payment_timed_out",
                        "created_at": 1724749200,
                    }
                }
            },
        }

        # Run Phase 1 pipeline
        norm_event, risk_event, root_cause = process_payment_failed_event(
            synthetic_webhook, in_memory_db
        )

        # Verify returned objects
        assert norm_event.event_id == "pay_synthetic_phase1_001"
        assert norm_event.amount == 25000.0
        assert risk_event.risk_id == "risk_pay_synthetic_phase1_001"
        assert risk_event.priority == Priority.HIGH
        assert root_cause.root_cause == RootCauseEnum.BANK_TIMEOUT

        # Verify database records directly via SQL query
        cursor = in_memory_db.cursor()
        cursor.execute("SELECT * FROM risk_events WHERE risk_id = ?", (risk_event.risk_id,))
        risk_row = cursor.fetchone()
        assert risk_row is not None
        assert risk_row["risk_id"] == "risk_pay_synthetic_phase1_001"
        assert risk_row["event_id"] == "pay_synthetic_phase1_001"
        assert risk_row["risk_type"] == "payment_failed"
        assert risk_row["amount"] == 25000.0
        assert risk_row["priority"] == "HIGH"
        assert risk_row["status"] == "DETECTED"

        cursor.execute("SELECT * FROM root_causes WHERE risk_id = ?", (risk_event.risk_id,))
        rc_row = cursor.fetchone()
        assert rc_row is not None
        assert rc_row["risk_id"] == "risk_pay_synthetic_phase1_001"
        assert rc_row["root_cause"] == "bank_timeout"
        assert rc_row["confidence"] == 1.0
        assert rc_row["source"] == "rule"
