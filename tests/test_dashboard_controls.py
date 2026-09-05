import os
import sqlite3
import pytest
from fastapi.testclient import TestClient
from src.server import app, _run_batch_worker, DB_PATH, LIVE_DB_PATH
from src.db import init_db
from src.metrics import get_summary_metrics


@pytest.fixture
def dashboard_client(tmp_path, monkeypatch):
    demo_db = str(tmp_path / "test_demo.db")
    live_db = str(tmp_path / "test_live.db")
    unatt_db = str(tmp_path / "test_unattributed.db")
    monkeypatch.setattr("src.server.DB_PATH", demo_db)
    monkeypatch.setattr("src.server.LIVE_DB_PATH", live_db)
    monkeypatch.setattr("src.server.UNATTRIBUTED_DB_PATH", unatt_db)

    # Initialize demo db
    conn = sqlite3.connect(demo_db)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.close()

    # Initialize live db with dummy live test record
    conn_live = sqlite3.connect(live_db)
    conn_live.row_factory = sqlite3.Row
    init_db(conn_live)
    with conn_live:
        conn_live.execute("""
            INSERT INTO risk_events (risk_id, event_id, risk_type, amount, priority, status, created_at)
            VALUES ('risk_live_rzp_final_001', 'live_001', 'payment_failed', 100.0, 'LOW', 'RECOVERED', '2026-09-04T16:57:53');
        """)
        conn_live.execute("""
            INSERT INTO outcomes (risk_id, action_index, result, amount_recovered, resolved_at)
            VALUES ('risk_live_rzp_final_001', 0, 'SUCCESS', 100.0, '2026-09-04T17:00:05');
        """)
    conn_live.close()

    # Initialize unattributed db
    conn_unatt = sqlite3.connect(unatt_db)
    conn_unatt.row_factory = sqlite3.Row
    init_db(conn_unatt)
    conn_unatt.close()

    return TestClient(app), demo_db, live_db


def test_reset_yields_zero_metrics_and_empty_list(dashboard_client):
    client, demo_db, live_db = dashboard_client

    # Call reset
    reset_res = client.post("/api/batch/reset")
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "reset_successful"

    # 1. Verify zero metrics
    m_res = client.get("/api/metrics?view=demo")
    assert m_res.status_code == 200
    metrics = m_res.json()
    assert metrics["transactions_count"] == 0
    assert metrics["total_revenue_at_risk"] == 0.0
    assert metrics["total_revenue_recovered"] == 0.0
    assert metrics["recovery_rate_pct"] == 0.0
    assert metrics["recovered_count"] == 0
    assert metrics["guardrail_blocks_count"] == 0
    assert metrics["escalations_count"] == 0

    # 2. Verify empty transaction list
    tx_res = client.get("/api/transactions?view=demo")
    assert tx_res.status_code == 200
    assert tx_res.json() == []


def test_synthetic_batch_produces_exact_canonical_baseline(dashboard_client):
    client, demo_db, live_db = dashboard_client

    # Clean reset first
    client.post("/api/batch/reset")

    # Run batch worker
    _run_batch_worker(batch_size=65, delay_s=0.0)

    # 3. Verify exact canonical metrics
    m_res = client.get("/api/metrics?view=demo")
    assert m_res.status_code == 200
    metrics = m_res.json()
    assert metrics["transactions_count"] == 65
    assert metrics["total_revenue_at_risk"] == 650037.0
    assert metrics["total_revenue_recovered"] == 391725.0
    assert metrics["recovery_rate_pct"] == 60.26
    assert metrics["recovered_count"] == 48
    assert metrics["guardrail_blocks_count"] == 8
    assert metrics["escalations_count"] == 17

    # Verify transaction count is 65
    tx_res = client.get("/api/transactions?view=demo")
    assert tx_res.status_code == 200
    assert len(tx_res.json()) == 65


def test_synthetic_batch_repeated_execution_is_idempotent(dashboard_client):
    client, demo_db, live_db = dashboard_client

    # Clean reset and populate 65 events
    client.post("/api/batch/reset")
    _run_batch_worker(batch_size=65, delay_s=0.0)

    # 4. Trigger batch run API again
    run_res = client.post("/api/batch/run?size=65&speed=fast")
    assert run_res.status_code == 200
    data = run_res.json()
    assert data["status"] == "already_loaded"
    assert data["processed"] == 65

    # Verify metrics did not duplicate
    m_res = client.get("/api/metrics?view=demo")
    metrics = m_res.json()
    assert metrics["transactions_count"] == 65
    assert metrics["total_revenue_at_risk"] == 650037.0
    assert metrics["total_revenue_recovered"] == 391725.0
    assert metrics["recovery_rate_pct"] == 60.26


def test_recovery_rate_calculation_remains_amount_based():
    # 5. Recovery rate calculation remains amount-based
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    with conn:
        # 2 transactions, 1 recovered
        conn.execute("""
            INSERT INTO risk_events (risk_id, event_id, risk_type, amount, priority, status, created_at)
            VALUES ('tx1', 'e1', 'payment_failed', 1000.0, 'HIGH', 'RECOVERED', '2026-09-04T10:00:00'),
                   ('tx2', 'e2', 'payment_failed', 9000.0, 'HIGH', 'FAILED', '2026-09-04T10:00:00');
        """)
        conn.execute("""
            INSERT INTO outcomes (risk_id, action_index, result, amount_recovered, resolved_at)
            VALUES ('tx1', 0, 'SUCCESS', 1000.0, '2026-09-04T10:05:00');
        """)
    m = get_summary_metrics(conn)
    # Total at risk = 10,000, total recovered = 1,000 => 10.0% (NOT 50% transaction count)
    assert m["total_revenue_at_risk"] == 10000.0
    assert m["total_revenue_recovered"] == 1000.0
    assert m["recovery_rate_pct"] == 10.0
    conn.close()


def test_live_razorpay_evidence_preserved_across_demo_resets(dashboard_client):
    client, demo_db, live_db = dashboard_client

    # Verify live record exists
    live_res = client.get("/api/metrics?view=live")
    assert live_res.status_code == 200
    assert live_res.json()["transactions_count"] == 1
    assert live_res.json()["total_revenue_recovered"] == 100.0

    # 6. Execute demo reset
    client.post("/api/batch/reset")

    # Verify demo is reset to 0
    demo_res = client.get("/api/metrics?view=demo")
    assert demo_res.json()["transactions_count"] == 0

    # Verify live record is completely preserved and unaffected
    live_res_after = client.get("/api/metrics?view=live")
    assert live_res_after.json()["transactions_count"] == 1
    assert live_res_after.json()["total_revenue_recovered"] == 100.0

    # Verify live transaction detail drilldown works
    tx_detail = client.get("/api/transactions/risk_live_rzp_final_001")
    assert tx_detail.status_code == 200
    assert tx_detail.json()["risk_id"] == "risk_live_rzp_final_001"
    assert tx_detail.json()["status"] == "RECOVERED"


def test_rerun_synthetic_batch_pathway_preserves_canonical_65_not_130(dashboard_client):
    client, demo_db, live_db = dashboard_client

    # First run: Clean reset + run batch
    client.post("/api/batch/reset")
    _run_batch_worker(batch_size=65, delay_s=0.0)

    m1 = client.get("/api/metrics?view=demo").json()
    assert m1["transactions_count"] == 65
    assert m1["total_revenue_at_risk"] == 650037.0
    assert m1["total_revenue_recovered"] == 391725.0
    assert m1["recovery_rate_pct"] == 60.26

    # Secondary action: Re-run flow (Reset + Run)
    client.post("/api/batch/reset")
    _run_batch_worker(batch_size=65, delay_s=0.0)

    # Verify exactly 65 records, NOT 130!
    m2 = client.get("/api/metrics?view=demo").json()
    assert m2["transactions_count"] == 65
    assert m2["total_revenue_at_risk"] == 650037.0
    assert m2["total_revenue_recovered"] == 391725.0
    assert m2["recovery_rate_pct"] == 60.26
    assert m2["recovered_count"] == 48
    assert m2["guardrail_blocks_count"] == 8
    assert m2["escalations_count"] == 17

    tx_res = client.get("/api/transactions?view=demo").json()
    assert len(tx_res) == 65

    # Verify live database remains completely untouched
    live_res = client.get("/api/metrics?view=live").json()
    assert live_res["transactions_count"] == 1
    assert live_res["total_revenue_recovered"] == 100.0


def test_synthetic_events_use_mock_execution_without_external_calls(dashboard_client):
    from src.models import ActionType, ExecutionStatusEnum
    from src.executor import execute_action

    client, demo_db, live_db = dashboard_client
    conn = sqlite3.connect(demo_db)
    conn.row_factory = sqlite3.Row

    # Even in sandbox mode, synthetic risk_ids (risk_pay_syn_*) MUST execute mock without calling Razorpay
    os.environ["EXECUTION_MODE"] = "sandbox"
    result = execute_action(
        conn=conn,
        risk_id="risk_pay_syn_9999",
        action_index=0,
        action_type=ActionType.PAYMENT_LINK,
        amount=500.0,
        customer_id="cust_syn_9999",
        simulate_status=ExecutionStatusEnum.SUCCESS,
        metadata={"channel": "email"},
    )
    assert result.status == ExecutionStatusEnum.SUCCESS
    assert result.details["simulated"] is True
    assert result.details["action"] == "payment_link"
    assert "plink_" in result.details["payment_link_id"]
    conn.close()


def test_frontend_does_not_use_native_window_confirm(dashboard_client):
    client, demo_db, live_db = dashboard_client
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    # Native window.confirm must NOT be present
    assert 'confirm("Reset database state for clean test run?")' not in html
    assert 'window.confirm' not in html
    # Inline confirmation elements must be present
    assert 'btn-confirm-reset' in html
    assert 'btn-cancel-reset' in html
    assert 'btn-confirm-rerun' in html
    assert 'btn-cancel-rerun' in html
    assert 'Reset synthetic demo data?' in html
    assert 'Re-run the canonical 65-event demo from a clean state?' in html


def test_synthetic_payment_link_never_calls_razorpay_api_and_uses_mock(dashboard_client):
    from unittest.mock import patch
    from src.models import ActionType, ExecutionStatusEnum
    from src.executor import execute_action
    from src.integrations.razorpay_client import RazorpayClientAdapter

    client, demo_db, live_db = dashboard_client
    conn = sqlite3.connect(demo_db)
    conn.row_factory = sqlite3.Row

    with patch.dict(os.environ, {"EXECUTION_MODE": "sandbox"}):
        with patch.object(RazorpayClientAdapter, "create_payment_link") as mock_link:
            res = execute_action(
                conn=conn,
                risk_id="risk_pay_syn_1020",
                action_index=1,
                action_type=ActionType.PAYMENT_LINK,
                amount=12164.0,
                customer_id="cust_1020",
                simulate_status=ExecutionStatusEnum.SUCCESS,
            )
            # 1. Razorpay API is NEVER called for synthetic IDs
            mock_link.assert_not_called()
            # 2. Details strictly declare mock execution
            assert res.details["execution_mode"] == "mock"
            assert res.details["simulated"] is True
            assert res.status == ExecutionStatusEnum.SUCCESS
            assert "plink_" in res.details["payment_link_id"]

            # 3. Verify audit log entry also states execution_mode='mock'
            c = conn.cursor()
            c.execute("SELECT input_json, output_json FROM audit_log WHERE risk_id = 'risk_pay_syn_1020' AND layer = 'action_executor'")
            row = c.fetchone()
            assert row is not None
            assert '"execution_mode": "mock"' in row[0]
            assert '"execution_mode": "mock"' in row[1]
    conn.close()


def test_sandbox_executor_rejects_synthetic_risk_id():
    from src.integrations.sandbox_executor import execute_sandbox_payment_link

    with pytest.raises(ValueError) as exc_info:
        execute_sandbox_payment_link(
            risk_id="risk_pay_syn_1020",
            amount=12164.0,
            customer_id="cust_1020",
        )
    assert "Routing Invariant Violation" in str(exc_info.value)
    assert "Synthetic risk event 'risk_pay_syn_1020' cannot be executed with Razorpay Sandbox" in str(exc_info.value)


def test_live_payment_link_uses_sandbox_executor_with_simulated_false(dashboard_client):
    from unittest.mock import patch
    from src.models import ActionType, ExecutionStatusEnum
    from src.executor import execute_action
    from src.integrations.razorpay_client import RazorpayClientAdapter

    client, demo_db, live_db = dashboard_client
    conn = sqlite3.connect(live_db)
    conn.row_factory = sqlite3.Row

    with patch.dict(os.environ, {"EXECUTION_MODE": "sandbox"}):
        with patch.object(RazorpayClientAdapter, "create_payment_link") as mock_link:
            mock_link.return_value = {
                "payment_link_id": "plink_live_sbx_test_999",
                "short_url": "https://rzp.io/i/plink_live_sbx_test_999",
                "status": "created",
            }
            res = execute_action(
                conn=conn,
                risk_id="risk_live_test_002",
                action_index=0,
                action_type=ActionType.PAYMENT_LINK,
                amount=250.0,
                customer_id="cust_live_002",
                simulate_status=ExecutionStatusEnum.SUCCESS,
            )
            # 1. Razorpay API was called
            mock_link.assert_called_once()
            # 2. Details strictly declare sandbox with simulated=False
            assert res.details["execution_mode"] == "sandbox"
            assert res.details["simulated"] is False
            assert res.details["payment_link_id"] == "plink_live_sbx_test_999"

            # 3. Verify audit log entry states execution_mode='sandbox'
            c = conn.cursor()
            c.execute("SELECT input_json, output_json FROM audit_log WHERE risk_id = 'risk_live_test_002' AND layer = 'action_executor'")
            row = c.fetchone()
            assert row is not None
            assert '"execution_mode": "sandbox"' in row[0]
            assert '"execution_mode": "sandbox"' in row[1]
    conn.close()


def test_synthetic_batch_with_sandbox_mode_never_calls_razorpay_api(dashboard_client):
    from unittest.mock import patch
    from src.integrations.razorpay_client import RazorpayClientAdapter

    client, demo_db, live_db = dashboard_client
    client.post("/api/batch/reset")

    with patch.dict(os.environ, {"EXECUTION_MODE": "sandbox"}):
        with patch.object(RazorpayClientAdapter, "create_payment_link") as mock_link:
            _run_batch_worker(batch_size=65, delay_s=0.0)
            # Batch of 65 events executed without calling Razorpay API even once
            assert mock_link.call_count == 0

    m = client.get("/api/metrics?view=demo").json()
    assert m["transactions_count"] == 65
    assert m["total_revenue_at_risk"] == 650037.0
    assert m["total_revenue_recovered"] == 391725.0
    assert m["recovery_rate_pct"] == 60.26
    assert m["recovered_count"] == 48
    assert m["guardrail_blocks_count"] == 8
    assert m["escalations_count"] == 17


def test_live_razorpay_db_isolated_from_synthetic_webhooks(dashboard_client):
    import json
    import hmac
    import hashlib
    from unittest.mock import patch

    client, demo_db, live_db = dashboard_client
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "test_secret")

    body_dict = {
        "event": "payment.captured",
        "event_id": "evt_syn_isolated_test_1",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_syn_isolation_01",
                    "amount": 1216400,
                    "notes": {
                        "reference_id": "risk_pay_syn_1020",
                        "customer_id": "cust_1020",
                    },
                }
            }
        },
    }
    body_str = json.dumps(body_dict)
    sig = hmac.new(webhook_secret.encode("utf-8"), body_str.encode("utf-8"), hashlib.sha256).hexdigest()

    with patch("src.webhook.verify_webhook_signature", return_value=True):
        res = client.post(
            "/api/webhooks/razorpay",
            content=body_str,
            headers={"x-razorpay-signature": sig, "content-type": "application/json"},
        )
        assert res.status_code == 200

    # Verify live_razorpay.db was NOT contaminated
    live_conn = sqlite3.connect(live_db)
    c = live_conn.cursor()
    c.execute("SELECT count(*) FROM risk_events WHERE risk_id = 'risk_pay_syn_1020'")
    assert c.fetchone()[0] == 0
    c.execute("SELECT count(*) FROM audit_log WHERE risk_id = 'risk_pay_syn_1020'")
    assert c.fetchone()[0] == 0
    # Live db retains only canonical risk_live_rzp_final_001
    c.execute("SELECT count(*) FROM risk_events")
    assert c.fetchone()[0] == 1
    live_conn.close()


# ==============================================================================
# FINAL WEBHOOK PROVENANCE HARDENING TESTS (TESTS 1 to 9)
# ==============================================================================

def test_webhook_provenance_test_1_notes_empty_dict():
    """
    TEST 1:
    notes = {}
    -> reference extraction works/falls through.
    """
    from src.webhook import extract_reference_id

    # notes = {} alone returns None without throwing
    payload_empty = {"payload": {"payment": {"entity": {"notes": {}}}}}
    assert extract_reference_id(payload_empty) is None

    # payment.notes = {}, order.notes has valid risk ID -> falls through cleanly
    payload_fallthrough = {
        "payload": {
            "payment": {"entity": {"notes": {}}},
            "order": {"entity": {"notes": {"reference_id": "risk_live_order_001"}}},
        }
    }
    assert extract_reference_id(payload_fallthrough) == "risk_live_order_001"


def test_webhook_provenance_test_2_notes_empty_list():
    """
    TEST 2:
    notes = []
    -> no exception (specifically avoids AttributeError: 'list' object has no attribute 'get').
    """
    from src.webhook import extract_reference_id

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_list_notes",
                    "notes": [],
                }
            }
        }
    }
    assert extract_reference_id(payload) is None


def test_webhook_provenance_test_3_notes_none():
    """
    TEST 3:
    notes = None
    -> no exception.
    """
    from src.webhook import extract_reference_id

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_none_notes",
                    "notes": None,
                }
            }
        }
    }
    assert extract_reference_id(payload) is None


def test_webhook_provenance_test_4_order_notes_list():
    """
    TEST 4:
    order.notes = []
    -> no exception.
    """
    from src.webhook import extract_reference_id

    payload = {
        "event": "order.paid",
        "payload": {
            "order": {
                "entity": {
                    "id": "order_test_list_notes",
                    "notes": [],
                }
            }
        }
    }
    assert extract_reference_id(payload) is None


def test_webhook_provenance_test_5_recovered_from_order_receipt():
    """
    TEST 5:
    payment.notes = []
    order.receipt = "risk_live_test_001"
    -> reference ID is correctly recovered from order.receipt.
    """
    from src.webhook import extract_reference_id

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_rcpt_001",
                    "notes": [],
                }
            },
            "order": {
                "entity": {
                    "id": "order_test_rcpt_001",
                    "receipt": "risk_live_test_001",
                    "notes": [],
                }
            },
        },
    }
    ref = extract_reference_id(payload)
    assert ref == "risk_live_test_001"


def test_webhook_provenance_test_6_no_usable_provenance_quarantined_not_demo(dashboard_client):
    """
    TEST 6:
    no usable provenance anywhere
    -> event is NOT silently routed to recovery.db as demo.
    It is routed to unattributed_webhooks.db (quarantine).
    """
    import json
    from unittest.mock import patch
    import src.server

    client, demo_db, live_db = dashboard_client
    unatt_db = src.server.UNATTRIBUTED_DB_PATH

    body_dict = {
        "event": "payment.captured",
        "event_id": "evt_quarantine_test_006",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_no_provenance_006",
                    "amount": 50000,
                    "notes": [],
                }
            },
            "order": {
                "entity": {
                    "id": "order_no_provenance_006",
                    "notes": None,
                }
            }
        }
    }
    body_str = json.dumps(body_dict)

    with patch("src.webhook.verify_webhook_signature", return_value=True):
        res = client.post(
            "/api/webhooks/razorpay",
            content=body_str,
            headers={"x-razorpay-signature": "valid_sig", "content-type": "application/json"},
        )
        assert res.status_code == 200

    # 1. Verify event is NOT in demo db (recovery.db)
    demo_conn = sqlite3.connect(demo_db)
    dc = demo_conn.cursor()
    dc.execute("SELECT count(*) FROM webhook_events WHERE event_id = 'evt_quarantine_test_006'")
    assert dc.fetchone()[0] == 0
    dc.execute("SELECT count(*) FROM audit_log WHERE input_json LIKE '%evt_quarantine_test_006%'")
    assert dc.fetchone()[0] == 0
    demo_conn.close()

    # 2. Verify event is NOT in live db
    live_conn = sqlite3.connect(live_db)
    lc = live_conn.cursor()
    lc.execute("SELECT count(*) FROM webhook_events WHERE event_id = 'evt_quarantine_test_006'")
    assert lc.fetchone()[0] == 0
    live_conn.close()

    # 3. Verify event IS recorded in unattributed quarantine db
    unatt_conn = sqlite3.connect(unatt_db)
    uc = unatt_conn.cursor()
    uc.execute("SELECT processing_status FROM webhook_events WHERE event_id = 'evt_quarantine_test_006'")
    row = uc.fetchone()
    assert row is not None
    assert row[0] == "PROCESSED"
    unatt_conn.close()


def test_webhook_provenance_test_7_valid_risk_live_routes_to_live_db(dashboard_client):
    """
    TEST 7:
    valid risk_live_* provenance
    -> live_razorpay.db.
    """
    import json
    from unittest.mock import patch

    client, demo_db, live_db = dashboard_client

    body_dict = {
        "event": "payment.captured",
        "event_id": "evt_live_test_007",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_live_007",
                    "amount": 25000,
                    "notes": {
                        "reference_id": "risk_live_rzp_test_007",
                    }
                }
            }
        }
    }
    body_str = json.dumps(body_dict)

    with patch("src.webhook.verify_webhook_signature", return_value=True):
        res = client.post(
            "/api/webhooks/razorpay",
            content=body_str,
            headers={"x-razorpay-signature": "valid_sig", "content-type": "application/json"},
        )
        assert res.status_code == 200

    # Verify event IS recorded in live db
    live_conn = sqlite3.connect(live_db)
    lc = live_conn.cursor()
    lc.execute("SELECT processing_status FROM webhook_events WHERE event_id = 'evt_live_test_007'")
    row = lc.fetchone()
    assert row is not None
    assert row[0] == "PROCESSED"
    live_conn.close()

    # Verify demo db was NOT touched
    demo_conn = sqlite3.connect(demo_db)
    dc = demo_conn.cursor()
    dc.execute("SELECT count(*) FROM webhook_events WHERE event_id = 'evt_live_test_007'")
    assert dc.fetchone()[0] == 0
    demo_conn.close()


def test_webhook_provenance_test_8_synthetic_risk_pay_syn_routes_to_recovery_db(dashboard_client):
    """
    TEST 8:
    synthetic risk_pay_syn_* provenance
    -> recovery.db.
    """
    import json
    from unittest.mock import patch

    client, demo_db, live_db = dashboard_client

    body_dict = {
        "event": "payment.captured",
        "event_id": "evt_syn_test_008",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_syn_008",
                    "amount": 100000,
                    "notes": {
                        "reference_id": "risk_pay_syn_9999",
                    }
                }
            }
        }
    }
    body_str = json.dumps(body_dict)

    with patch("src.webhook.verify_webhook_signature", return_value=True):
        res = client.post(
            "/api/webhooks/razorpay",
            content=body_str,
            headers={"x-razorpay-signature": "valid_sig", "content-type": "application/json"},
        )
        assert res.status_code == 200

    # Verify event IS in demo db
    demo_conn = sqlite3.connect(demo_db)
    dc = demo_conn.cursor()
    dc.execute("SELECT processing_status FROM webhook_events WHERE event_id = 'evt_syn_test_008'")
    row = dc.fetchone()
    assert row is not None
    assert row[0] == "PROCESSED"
    demo_conn.close()

    # Verify event is NOT in live db
    live_conn = sqlite3.connect(live_db)
    lc = live_conn.cursor()
    lc.execute("SELECT count(*) FROM webhook_events WHERE event_id = 'evt_syn_test_008'")
    assert lc.fetchone()[0] == 0
    live_conn.close()


def test_webhook_provenance_test_9_canonical_live_transaction_remains_untouched():
    """
    TEST 9:
    existing genuine live transaction
    risk_live_rzp_final_001
    remains untouched in actual live_razorpay.db.
    """
    live_db_path = "live_razorpay.db"
    assert os.path.exists(live_db_path), "live_razorpay.db must exist"

    conn = sqlite3.connect(live_db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT risk_id, amount, status FROM risk_events WHERE risk_id = 'risk_live_rzp_final_001'")
    row = c.fetchone()
    assert row is not None, "risk_live_rzp_final_001 must exist in live_razorpay.db"
    assert row["amount"] == 100.0
    assert row["status"] == "RECOVERED"

    c.execute("SELECT result, amount_recovered FROM outcomes WHERE risk_id = 'risk_live_rzp_final_001'")
    out_row = c.fetchone()
    assert out_row is not None
    assert out_row["result"] == "SUCCESS"
    assert out_row["amount_recovered"] == 100.0

    # Ensure risk_live_rzp_final_002 was not artificially repaired into live_razorpay.db
    c.execute("SELECT count(*) FROM risk_events WHERE risk_id = 'risk_live_rzp_final_002'")
    assert c.fetchone()[0] == 0
    conn.close()


