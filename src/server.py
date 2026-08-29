import sqlite3
import threading
import os
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

from src.db import init_db, get_db_connection
from src.metrics import (
    get_summary_metrics,
    get_root_cause_breakdown,
    get_action_performance_breakdown,
    get_escalation_and_block_summary,
    get_transactions_list,
    get_transaction_detail,
)
from src.batch_runner import run_synthetic_batch, generate_synthetic_batch
from src.integrations.config import get_feature_flags_status
from src.webhook import process_webhook


DB_PATH = "recovery.db"

# Batch execution state
batch_state: Dict[str, Any] = {
    "is_running": False,
    "total": 0,
    "processed": 0,
    "last_run_time": None,
    "error": None,
}
batch_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    conn = get_db_connection(DB_PATH)
    init_db(conn)
    return conn


def _run_batch_worker(batch_size: int = 65, delay_s: float = 0.05):
    global batch_state
    try:
        conn = get_connection()
        batch = generate_synthetic_batch(batch_size)
        with batch_lock:
            batch_state["is_running"] = True
            batch_state["total"] = len(batch)
            batch_state["processed"] = 0
            batch_state["error"] = None

        def progress_callback(event_summary):
            with batch_lock:
                batch_state["processed"] += 1

        run_synthetic_batch(
            conn=conn,
            batch=batch,
            delay_between_events_s=delay_s,
            callback=progress_callback,
        )
        conn.close()
    except Exception as e:
        with batch_lock:
            batch_state["error"] = str(e)
    finally:
        with batch_lock:
            batch_state["is_running"] = False
            batch_state["last_run_time"] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection()
    conn.close()
    yield


app = FastAPI(title="AI Revenue Recovery System", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/config/mode")
def api_config_mode():
    """Returns current execution mode and active feature flag status."""
    return get_feature_flags_status()


@app.post("/api/webhooks/razorpay")
async def api_razorpay_webhook(request: Request):
    """
    Razorpay Webhook endpoint with HMAC signature verification,
    event deduplication, and lifecycle tracking.
    """
    raw_body_bytes = await request.body()
    raw_body = raw_body_bytes.decode("utf-8")
    headers = dict(request.headers)

    conn = get_connection()
    try:
        res = process_webhook(conn, raw_body=raw_body, headers=headers)
        return res
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {str(exc)}")
    finally:
        conn.close()


@app.get("/api/metrics")
def api_metrics():
    conn = get_connection()
    try:
        metrics = get_summary_metrics(conn)
        return metrics
    finally:
        conn.close()


@app.get("/api/breakdown/root-cause")
def api_root_cause_breakdown():
    conn = get_connection()
    try:
        return get_root_cause_breakdown(conn)
    finally:
        conn.close()


@app.get("/api/breakdown/actions")
def api_actions_breakdown():
    conn = get_connection()
    try:
        return get_action_performance_breakdown(conn)
    finally:
        conn.close()


@app.get("/api/breakdown/escalations")
def api_escalations_breakdown():
    conn = get_connection()
    try:
        return get_escalation_and_block_summary(conn)
    finally:
        conn.close()


@app.get("/api/transactions")
def api_transactions(limit: int = 200):
    conn = get_connection()
    try:
        return get_transactions_list(conn, limit=limit)
    finally:
        conn.close()


@app.get("/api/transactions/{risk_id}")
def api_transaction_detail(risk_id: str):
    conn = get_connection()
    try:
        detail = get_transaction_detail(conn, risk_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return detail
    finally:
        conn.close()


@app.post("/api/batch/run")
def api_run_batch(background_tasks: BackgroundTasks, size: int = 65, speed: str = "normal"):
    global batch_state
    with batch_lock:
        if batch_state["is_running"]:
            return {"status": "already_running", "processed": batch_state["processed"], "total": batch_state["total"]}

    delay = 0.05 if speed == "normal" else 0.0
    background_tasks.add_task(_run_batch_worker, batch_size=size, delay_s=delay)
    return {"status": "started", "size": size}


@app.post("/api/b2b/receivables")
async def api_process_b2b_receivable(receivable_data: Dict[str, Any]):
    """Ingest and process a B2B receivable. Gated by B2B_ENABLED."""
    from src.integrations.config import is_b2b_enabled
    if not is_b2b_enabled():
        raise HTTPException(status_code=403, detail="B2B Receivables Recovery is disabled (B2B_ENABLED=false)")

    conn = get_connection()
    try:
        from src.receivables import process_b2b_receivable
        res = process_b2b_receivable(conn, receivable_data)
        return res
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"B2B processing error: {str(exc)}")
    finally:
        conn.close()


@app.get("/api/b2b/receivables")
def api_list_b2b_receivables():
    """List all B2B receivables. Gated by B2B_ENABLED."""
    from src.integrations.config import is_b2b_enabled
    if not is_b2b_enabled():
        raise HTTPException(status_code=403, detail="B2B Receivables Recovery is disabled (B2B_ENABLED=false)")

    conn = get_connection()
    try:
        from src.db import list_receivables
        return [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in list_receivables(conn)]
    finally:
        conn.close()


@app.get("/api/metrics/b2b")
def api_b2b_metrics():
    """B2B summary metrics. Gated by B2B_ENABLED."""
    from src.integrations.config import is_b2b_enabled
    if not is_b2b_enabled():
        raise HTTPException(status_code=403, detail="B2B Receivables Recovery is disabled (B2B_ENABLED=false)")

    conn = get_connection()
    try:
        from src.db import list_receivables
        recs = list_receivables(conn)
        total_count = len(recs)
        total_due = sum(r.amount_due for r in recs)
        total_recovered = sum(r.amount_due for r in recs if r.status.value == "recovered")
        recovery_rate = (total_recovered / total_due * 100.0) if total_due > 0 else 0.0

        status_breakdown = {}
        for r in recs:
            st = r.status.value
            status_breakdown[st] = status_breakdown.get(st, 0) + 1

        return {
            "total_receivables": total_count,
            "total_amount_due": total_due,
            "total_recovered": total_recovered,
            "recovery_rate": round(recovery_rate, 2),
            "status_breakdown": status_breakdown,
        }
    finally:
        conn.close()


@app.post("/api/info-requests/{risk_id}/respond")
async def api_respond_info_request(risk_id: str, body: Dict[str, Any]):
    """Submits customer clarification response for an UNKNOWN root cause risk event. Gated by INFO_GATHERING_ENABLED."""
    from src.integrations.config import is_info_gathering_enabled
    if not is_info_gathering_enabled():
        raise HTTPException(status_code=403, detail="Information Gathering is disabled (INFO_GATHERING_ENABLED=false)")

    response_text = body.get("response", "")
    conn = get_connection()
    try:
        from src.info_gathering import process_customer_info_response
        res = process_customer_info_response(conn, risk_id, response_text)
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error processing info response: {str(exc)}")
    finally:
        conn.close()


@app.get("/api/info-requests/{risk_id}")
def api_get_info_request(risk_id: str):
    """Retrieves info request status. Gated by INFO_GATHERING_ENABLED."""
    from src.integrations.config import is_info_gathering_enabled
    if not is_info_gathering_enabled():
        raise HTTPException(status_code=403, detail="Information Gathering is disabled (INFO_GATHERING_ENABLED=false)")

    conn = get_connection()
    try:
        from src.db import get_info_request
        req = get_info_request(conn, risk_id)
        if not req:
            raise HTTPException(status_code=404, detail="Info request not found")
        return req.model_dump() if hasattr(req, "model_dump") else req.dict()
    finally:
        conn.close()


@app.post("/api/voice/call")
async def api_initiate_voice_call(body: Dict[str, Any]):
    """Initiates an outbound Hinglish voice call. Gated by VOICE_ENABLED."""
    from src.integrations.config import is_voice_enabled
    if not is_voice_enabled():
        raise HTTPException(status_code=403, detail="Hinglish Voice Recovery is disabled (VOICE_ENABLED=false)")

    risk_id = body.get("risk_id", "")
    phone_number = body.get("phone_number", "+919876543210")
    conn = get_connection()
    try:
        from src.voice import initiate_outbound_voice_call
        res = initiate_outbound_voice_call(conn, risk_id, phone_number)
        return res
    finally:
        conn.close()


@app.post("/api/voice/interact")
async def api_voice_interact(body: Dict[str, Any]):
    """Processes Hinglish voice transcript input and executes appropriate recovery action. Gated by VOICE_ENABLED."""
    from src.integrations.config import is_voice_enabled
    if not is_voice_enabled():
        raise HTTPException(status_code=403, detail="Hinglish Voice Recovery is disabled (VOICE_ENABLED=false)")

    risk_id = body.get("risk_id", "")
    transcript = body.get("transcript", "")
    phone_number = body.get("phone_number", "+919876543210")
    conn = get_connection()
    try:
        from src.voice import process_voice_interaction
        res = process_voice_interaction(conn, risk_id, transcript, phone_number)
        return res
    finally:
        conn.close()


@app.post("/api/voice/webhook/incoming", response_class=Response)
async def api_voice_webhook_incoming():
    """Handles Twilio incoming voice call webhook. Returns TwiML response. Gated by VOICE_ENABLED."""
    from src.integrations.config import is_voice_enabled
    if not is_voice_enabled():
        raise HTTPException(status_code=403, detail="Hinglish Voice Recovery is disabled (VOICE_ENABLED=false)")

    from src.integrations.twilio_client import generate_twiml_response
    twiml = generate_twiml_response("Namaste! Autonomous Revenue Recovery engine me aapka swagat hai. Main aapki kya sahayata kar sakta hoon?", gather_input=True)
    return Response(content=twiml, media_type="application/xml")


@app.get("/api/voice/interactions/{risk_id}")
def api_get_voice_interactions(risk_id: str):
    """Retrieves voice interaction history for a risk event. Gated by VOICE_ENABLED."""
    from src.integrations.config import is_voice_enabled
    if not is_voice_enabled():
        raise HTTPException(status_code=403, detail="Hinglish Voice Recovery is disabled (VOICE_ENABLED=false)")

    conn = get_connection()
    try:
        from src.db import list_voice_interactions_for_risk
        interactions = list_voice_interactions_for_risk(conn, risk_id)
        return [i.model_dump() if hasattr(i, "model_dump") else i.dict() for i in interactions]
    finally:
        conn.close()


@app.post("/api/batch/reset")
def api_reset_db():
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM audit_log;")
            conn.execute("DELETE FROM outcomes;")
            conn.execute("DELETE FROM escalations;")
            conn.execute("DELETE FROM executions;")
            conn.execute("DELETE FROM guardrail_checks;")
            conn.execute("DELETE FROM interventions;")
            conn.execute("DELETE FROM root_causes;")
            conn.execute("DELETE FROM risk_events;")
            conn.execute("DELETE FROM webhook_events;")
            conn.execute("DELETE FROM receivables;")
            conn.execute("DELETE FROM info_requests;")
            conn.execute("DELETE FROM voice_interactions;")
        return {"status": "reset_successful"}
    finally:
        conn.close()


@app.get("/api/batch/status")
def api_batch_status():
    with batch_lock:
        return dict(batch_state)


# Serve React Frontend UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def serve_root():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>AI Revenue Recovery Dashboard API running</h1>")
