import pytest
import sqlite3
from src.db import init_db
from src.batch_runner import generate_synthetic_batch, run_synthetic_batch
from src.metrics import get_summary_metrics, get_transactions_list, get_transaction_detail


@pytest.fixture
def clean_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class TestPhase9DemoRehearsal:
    def test_rehearsal_batch_deterministic_reproducibility(self):
        batch1 = generate_synthetic_batch(size=65, seed=42)
        batch2 = generate_synthetic_batch(size=65, seed=42)
        assert len(batch1) == 65
        assert len(batch2) == 65

        # Verify exact structural match
        for ev1, ev2 in zip(batch1, batch2):
            assert ev1["payload"]["payment"]["entity"]["id"] == ev2["payload"]["payment"]["entity"]["id"]
            assert ev1["payload"]["payment"]["entity"]["amount"] == ev2["payload"]["payment"]["entity"]["amount"]
            assert ev1["payload"]["payment"]["entity"]["error_reason"] == ev2["payload"]["payment"]["entity"]["error_reason"]

    def test_double_rehearsal_produces_identical_metrics(self):
        """Proves two complete runs from clean state yield identical metrics."""
        conn1 = sqlite3.connect(":memory:")
        conn1.row_factory = sqlite3.Row
        init_db(conn1)
        batch1 = generate_synthetic_batch(size=65, seed=42)
        run_synthetic_batch(conn=conn1, batch=batch1)
        m1 = get_summary_metrics(conn1)
        conn1.close()

        conn2 = sqlite3.connect(":memory:")
        conn2.row_factory = sqlite3.Row
        init_db(conn2)
        batch2 = generate_synthetic_batch(size=65, seed=42)
        run_synthetic_batch(conn=conn2, batch=batch2)
        m2 = get_summary_metrics(conn2)
        conn2.close()

        assert m1 == m2
        assert m1["transactions_count"] == 65
        assert m1["recovered_count"] == 48
        assert m1["guardrail_blocks_count"] == 8
        assert m1["escalations_count"] == 17

    def test_demo_narratives_present_in_rehearsal_run(self, clean_db):
        """Verifies all four required demo narratives are present and verifiable."""
        batch = generate_synthetic_batch(size=65, seed=42)
        res = run_synthetic_batch(conn=clean_db, batch=batch)

        # Narrative 1: Multi-step recovery
        tx_list = get_transactions_list(clean_db, limit=100)
        multi_step = next((t for t in tx_list if t["executions_count"] == 2 and t["status"] == "RECOVERED"), None)
        assert multi_step is not None
        detail1 = get_transaction_detail(clean_db, multi_step["risk_id"])
        decisions1 = [e["decision"] for e in detail1["audit_trail"]]
        assert "revenue_recovered" in decisions1

        # Narrative 2: Guardrail compliance block
        blocked = next((t for t in tx_list if (t.get("escalation_reason") or "").startswith("guardrail_blocked")), None)
        assert blocked is not None
        detail2 = get_transaction_detail(clean_db, blocked["risk_id"])
        decisions2 = [e["decision"] for e in detail2["audit_trail"]]
        assert "guardrail_block" in decisions2
        assert "escalated" in decisions2

        # Narrative 3: LLM fallback success
        llm_event = next((e for e in res["events"] if e.get("source") == "llm"), None)
        assert llm_event is not None
        assert llm_event["status"] == "RECOVERED"

        # Narrative 4: LLM timeout safe fallback
        timeout_event = next((e for e in res["events"] if e.get("source") == "rule_fallback"), None)
        assert timeout_event is not None
        assert timeout_event["status"] == "ESCALATED"
