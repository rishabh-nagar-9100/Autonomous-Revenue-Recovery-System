import os
import json
import hmac
import hashlib
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.models import (
    ExecutionStatusEnum,
    ActionType,
    WebhookProcessingStatus,
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
)
from src.db import init_db, get_db_connection, insert_risk_event
from src.integrations.config import (
    ExecutionMode,
    get_execution_mode,
    get_feature_flags_status,
)
from src.integrations.razorpay_client import RazorpayClientAdapter
from src.integrations.sandbox_executor import execute_sandbox_payment_link
from src.executor import execute_action
from src.webhook import (
    verify_webhook_signature,
    extract_event_id,
    is_duplicate_event,
    process_webhook,
)
from src.reconciliation import reconcile_payment_status
from src.migrations import run_migrations
from src.server import app


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestPhase10MigrationsAndConfig:
    def test_migration_framework_initializes_schema(self, memory_db):
        cursor = memory_db.cursor()
        cursor.execute("SELECT version, name FROM schema_migrations ORDER BY version;")
        rows = cursor.fetchall()
        assert len(rows) >= 1
        assert rows[0]["name"] == "add_webhook_events"

        # Check webhook_events table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='webhook_events';")
        assert cursor.fetchone() is not None

    def test_feature_flags_defaults(self):
        status = get_feature_flags_status()
        assert status["execution_mode"] == "mock"
        assert status["b2b_enabled"] is False
        assert status["info_gathering_enabled"] is False
        assert status["voice_enabled"] is False
        assert status["fault_injection_enabled"] is False
        assert status["demo_fallback_to_mock"] is False


class TestPhase10RazorpayClientAdapter:
    @patch("razorpay.Client")
    def test_create_payment_link_success(self, mock_razorpay_client_cls):
        mock_client = MagicMock()
        mock_razorpay_client_cls.return_value = mock_client
        mock_client.payment_link.create.return_value = {
            "id": "plink_test12345",
            "short_url": "https://rzp.io/i/plink_test12345",
            "status": "created",
        }

        adapter = RazorpayClientAdapter(key_id="test_key", key_secret="test_secret")
        res = adapter.create_payment_link(amount=250.50, customer_id="cust_101")

        assert res["payment_link_id"] == "plink_test12345"
        assert res["short_url"] == "https://rzp.io/i/plink_test12345"

        # Verify paise conversion (250.50 * 100 = 25050)
        mock_client.payment_link.create.assert_called_once()
        call_args = mock_client.payment_link.create.call_args[1]["data"]
        assert call_args["amount"] == 25050
        assert call_args["currency"] == "INR"

    def test_webhook_signature_verification(self):
        secret = "test_webhook_secret_key"
        body = '{"event":"payment.captured","payload":{}}'

        # Compute valid HMAC signature
        valid_sig = hmac.new(
            key=secret.encode("utf-8"),
            msg=body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        adapter = RazorpayClientAdapter(webhook_secret=secret)
        assert adapter.verify_webhook_signature(body, valid_sig) is True
        assert adapter.verify_webhook_signature(body, "invalid_signature") is False


class TestPhase10SandboxExecutorAndStrictFallback:
    @patch.object(RazorpayClientAdapter, "create_payment_link")
    def test_sandbox_executor_success_path(self, mock_create_link):
        mock_create_link.return_value = {
            "payment_link_id": "plink_sandbox_999",
            "short_url": "https://rzp.io/i/plink_sandbox_999",
            "status": "created",
        }

        res = execute_sandbox_payment_link(
            risk_id="risk_sbx_1",
            amount=500.0,
            customer_id="cust_sbx",
        )
        assert res.status == ExecutionStatusEnum.SUCCESS
        assert res.details["payment_link_id"] == "plink_sandbox_999"
        assert res.details["execution_mode"] == "sandbox"
        assert res.details["simulated"] is False

    @patch.object(RazorpayClientAdapter, "create_payment_link")
    def test_strict_mode_separation_failure_without_fallback(self, mock_create_link):
        mock_create_link.side_effect = RuntimeError("Razorpay API Timeout")

        with patch("src.integrations.sandbox_executor.DEMO_FALLBACK_TO_MOCK", False):
            res = execute_sandbox_payment_link(
                risk_id="risk_sbx_err",
                amount=1000.0,
                customer_id="cust_err",
            )
            # Strict mode: Failure returns FAILED status, NO silent mock fallback
            assert res.status == ExecutionStatusEnum.FAILED
            assert res.details["fallback_applied"] is False
            assert "Razorpay API Timeout" in res.details["error"]

    @patch.object(RazorpayClientAdapter, "create_payment_link")
    def test_explicit_demo_fallback_to_mock_opt_in(self, mock_create_link):
        mock_create_link.side_effect = RuntimeError("Razorpay API Downtime")

        with patch("src.integrations.sandbox_executor.DEMO_FALLBACK_TO_MOCK", True):
            res = execute_sandbox_payment_link(
                risk_id="risk_demo_fb",
                amount=1000.0,
                customer_id="cust_demo",
            )
            # Explicit demo opt-in: fallback applied and logged
            assert res.status == ExecutionStatusEnum.SUCCESS
            assert res.details["fallback_applied"] is True
            assert "demo_mode_api_error" in res.details["fallback_reason"]

    def test_execution_mode_routing_in_executor(self, memory_db):
        # Default mock mode
        with patch.dict(os.environ, {"EXECUTION_MODE": "mock"}):
            res_mock = execute_action(
                risk_id="risk_route_1",
                action_index=0,
                action_type=ActionType.PAYMENT_LINK,
                amount=100.0,
                customer_id="cust_1",
                conn=memory_db,
            )
            assert res_mock.details["execution_mode"] == "mock"

        # Sandbox mode routing
        with patch.dict(os.environ, {"EXECUTION_MODE": "sandbox"}):
            with patch("src.integrations.sandbox_executor.RazorpayClientAdapter.create_payment_link") as mock_link:
                mock_link.return_value = {
                    "payment_link_id": "plink_routed",
                    "short_url": "https://rzp.io/i/plink_routed",
                    "status": "created",
                }
                res_sbx = execute_action(
                    risk_id="risk_route_2",
                    action_index=0,
                    action_type=ActionType.PAYMENT_LINK,
                    amount=100.0,
                    customer_id="cust_2",
                    conn=memory_db,
                )
                assert res_sbx.details["execution_mode"] == "sandbox"


class TestPhase10WebhookDeduplicationAndLifecycle:
    def test_webhook_deduplication_and_lifecycle_tracking(self, memory_db):
        secret = "wh_secret_key"
        body = json.dumps({"event": "payment.captured", "event_id": "evt_test_uniq_123"})
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers = {"x-razorpay-signature": sig, "x-razorpay-event-id": "evt_test_uniq_123"}

        # First receipt -> PROCESSED
        res1 = process_webhook(memory_db, raw_body=body, headers=headers, webhook_secret=secret)
        assert res1["status"] == "processed"
        assert res1["event_id"] == "evt_test_uniq_123"

        cursor = memory_db.cursor()
        cursor.execute("SELECT processing_status FROM webhook_events WHERE event_id = ?;", ("evt_test_uniq_123",))
        row = cursor.fetchone()
        assert row["processing_status"] == WebhookProcessingStatus.PROCESSED.value

        # Second receipt (duplicate) -> HTTP 200 duplicate_skipped
        res2 = process_webhook(memory_db, raw_body=body, headers=headers, webhook_secret=secret)
        assert res2["status"] == "duplicate_skipped"
        assert res2["event_id"] == "evt_test_uniq_123"

    def test_webhook_invalid_signature_raises(self, memory_db):
        body = json.dumps({"event": "payment.failed"})
        headers = {"x-razorpay-signature": "bad_sig"}
        with pytest.raises(ValueError, match="Invalid webhook signature"):
            process_webhook(memory_db, raw_body=body, headers=headers, webhook_secret="secret")


class TestPhase10ReconciliationAndMonotonicState:
    def test_reconciliation_updates_status_to_recovered(self, memory_db):
        risk = RiskEvent(
            risk_id="risk_recon_1",
            event_id="evt_recon_1",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=750.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
        )
        insert_risk_event(memory_db, risk)

        res = reconcile_payment_status(memory_db, risk_id="risk_recon_1", forced_status="RECOVERED")
        assert res["status"] == "reconciled"
        assert res["new_status"] == EventStatus.RECOVERED.value

        cursor = memory_db.cursor()
        cursor.execute("SELECT status FROM risk_events WHERE risk_id = ?;", ("risk_recon_1",))
        assert cursor.fetchone()["status"] == EventStatus.RECOVERED.value

    def test_monotonic_state_invariant_terminal_recovered_not_reverted(self, memory_db):
        risk = RiskEvent(
            risk_id="risk_recon_term",
            event_id="evt_recon_term",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=1200.0,
            priority=Priority.HIGH,
            status=EventStatus.RECOVERED,
        )
        insert_risk_event(memory_db, risk)

        # Attempting reconciliation on terminal RECOVERED state
        res = reconcile_payment_status(memory_db, risk_id="risk_recon_term", forced_status="RECOVERED")
        assert res["status"] == "already_recovered"

        cursor = memory_db.cursor()
        cursor.execute("SELECT status FROM risk_events WHERE risk_id = ?;", ("risk_recon_term",))
        assert cursor.fetchone()["status"] == EventStatus.RECOVERED.value


class TestPhase10FastAPIServerEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_config_mode_endpoint(self, client):
        response = client.get("/api/config/mode")
        assert response.status_code == 200
        data = response.json()
        assert "execution_mode" in data
        assert "b2b_enabled" in data

    def test_razorpay_webhook_endpoint_invalid_signature(self, client):
        response = client.post(
            "/api/webhooks/razorpay",
            content='{"event":"payment.failed"}',
            headers={"X-Razorpay-Signature": "invalid_sig"},
        )
        assert response.status_code == 400
        assert "Invalid webhook signature" in response.json()["detail"]

    def test_razorpay_webhook_endpoint_valid_and_duplicate(self, client):
        import uuid
        unique_evt_id = f"evt_api_test_{uuid.uuid4().hex[:8]}"
        secret = "dummy_webhook_secret"
        body = json.dumps({"event": "payment.authorized", "event_id": unique_evt_id})
        sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": unique_evt_id,
        }

        # Valid first webhook
        res1 = client.post("/api/webhooks/razorpay", content=body, headers=headers)
        assert res1.status_code == 200
        assert res1.json()["status"] == "processed"

        # Duplicate webhook -> HTTP 200 duplicate_skipped
        res2 = client.post("/api/webhooks/razorpay", content=body, headers=headers)
        assert res2.status_code == 200
        assert res2.json()["status"] == "duplicate_skipped"
