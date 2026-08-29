import pytest
import sqlite3
import json
from src.db import init_db, get_db_connection
from src.batch_runner import generate_synthetic_batch, run_synthetic_batch
from src.metrics import (
    get_summary_metrics,
    get_root_cause_breakdown,
    get_action_performance_breakdown,
    get_escalation_and_block_summary,
    get_transactions_list,
    get_transaction_detail,
)
from src.server import app
from fastapi.testclient import TestClient


@pytest.fixture
def in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_recovery.db")
    monkeypatch.setattr("src.server.DB_PATH", test_db)
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.close()
    return TestClient(app)


class TestBatchRunnerAndMetrics:
    def test_synthetic_batch_generation_criteria(self):
        batch = generate_synthetic_batch(60)
        assert len(batch) == 60

        error_reasons = {ev["payload"]["payment"]["entity"]["error_reason"] for ev in batch}
        # Verify coverage of all 6 root causes
        assert "payment_timed_out" in error_reasons  # bank_timeout
        assert "insufficient_funds" in error_reasons  # nsf
        assert "card_expired" in error_reasons        # expired_card
        assert "cart_abandoned" in error_reasons      # cart_abandonment
        assert "invoice_overdue_1_day" in error_reasons  # recent_overdue
        assert "chronic_defaulter" in error_reasons   # chronic_non_payer

    def test_run_synthetic_batch_updates_database_and_computes_metrics(self, in_memory_db):
        batch = generate_synthetic_batch(60)
        res = run_synthetic_batch(conn=in_memory_db, batch=batch)
        assert res["total_processed"] == 60

        metrics = get_summary_metrics(in_memory_db)
        assert metrics["transactions_count"] == 60
        assert metrics["total_revenue_at_risk"] > 0
        assert metrics["total_revenue_recovered"] > 0
        assert metrics["recovered_count"] > 0
        assert metrics["guardrail_blocks_count"] >= 1
        assert metrics["escalations_count"] >= 1

        # Check recovery rate math
        expected_rate = round((metrics["total_revenue_recovered"] / metrics["total_revenue_at_risk"]) * 100.0, 2)
        assert metrics["recovery_rate_pct"] == expected_rate

    def test_root_cause_and_action_breakdowns(self, in_memory_db):
        batch = generate_synthetic_batch(60)
        run_synthetic_batch(conn=in_memory_db, batch=batch)

        rc_breakdown = get_root_cause_breakdown(in_memory_db)
        assert len(rc_breakdown) >= 5
        for rc in rc_breakdown:
            assert "root_cause" in rc
            assert rc["count"] > 0
            assert rc["total_at_risk"] >= rc["recovered_amount"]

        act_breakdown = get_action_performance_breakdown(in_memory_db)
        assert len(act_breakdown) >= 1
        for act in act_breakdown:
            assert act["attempts"] == act["successes"] + act["failures"]

    def test_escalation_and_block_summary(self, in_memory_db):
        batch = generate_synthetic_batch(60)
        run_synthetic_batch(conn=in_memory_db, batch=batch)

        summary = get_escalation_and_block_summary(in_memory_db)
        assert "escalations_by_reason" in summary
        assert "blocks_by_reason" in summary
        assert len(summary["escalations_by_reason"]) > 0
        assert len(summary["blocks_by_reason"]) > 0

    def test_transaction_list_and_audit_drill_down(self, in_memory_db):
        batch = generate_synthetic_batch(60)
        run_synthetic_batch(conn=in_memory_db, batch=batch)

        tx_list = get_transactions_list(in_memory_db, limit=200)
        assert len(tx_list) == 60

        # Test drill-down for first transaction
        first_tx = tx_list[0]
        detail = get_transaction_detail(in_memory_db, first_tx["risk_id"])
        assert detail is not None
        assert detail["risk_id"] == first_tx["risk_id"]
        assert len(detail["audit_trail"]) > 0

        # Verify chronological ordering of audit trail
        ids = [entry["id"] for entry in detail["audit_trail"]]
        assert ids == sorted(ids)


class TestFastAPIServerEndpoints:
    def test_metrics_and_batch_endpoints(self, client):
        # 1. Initially empty
        res = client.get("/api/metrics")
        assert res.status_code == 200
        data = res.json()
        assert data["transactions_count"] == 0

        # 2. Run batch synchronous
        res = client.post("/api/batch/run?size=60&speed=fast")
        assert res.status_code == 200

        # Verify batch status endpoint
        st = client.get("/api/batch/status")
        assert st.status_code == 200

        # Let background task complete if any or run synchronous
        # Test transactions endpoint
        tx_res = client.get("/api/transactions")
        assert tx_res.status_code == 200

        # Test breakdown endpoints
        assert client.get("/api/breakdown/root-cause").status_code == 200
        assert client.get("/api/breakdown/actions").status_code == 200
        assert client.get("/api/breakdown/escalations").status_code == 200

        # Test root endpoint
        root_res = client.get("/")
        assert root_res.status_code == 200
