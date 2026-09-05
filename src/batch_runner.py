import sqlite3
import random
import json
import time
from unittest.mock import MagicMock
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from src.models import (
    ExecutionStatusEnum,
    RootCauseEnum,
    EventStatus,
)
from src.pipeline import process_payment_failed_event
from src.guardrails import GuardrailContext
from src.outcome_tracker import start_recovery_workflow


def create_deterministic_mock_llm_client():
    """Mock LLM client used during deterministic batch simulations."""
    def mock_create(*args, **kwargs):
        messages = kwargs.get("messages", [])
        prompt_content = messages[0]["content"] if messages else ""

        # If simulated timeout event
        if "SIMULATE_TIMEOUT" in prompt_content:
            raise TimeoutError("Anthropic API request timed out after 3.0s")

        # Context-based classification
        if "card validity" in prompt_content.lower() or "token expired" in prompt_content.lower():
            res_json = json.dumps({
                "root_cause": "expired_card",
                "confidence": 0.94,
                "reasoning": "Description states payment token expired on issuing network."
            })
        elif "liquidity" in prompt_content.lower() or "balance" in prompt_content.lower():
            res_json = json.dumps({
                "root_cause": "nsf",
                "confidence": 0.91,
                "reasoning": "Description refers to liquidity and account balance constraints."
            })
        else:
            res_json = json.dumps({
                "root_cause": "bank_timeout",
                "confidence": 0.88,
                "reasoning": "Intermittent network drop diagnosed from partner logs."
            })

        mock_block = MagicMock()
        mock_block.text = res_json
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        return mock_resp

    client = MagicMock()
    client.messages.create.side_effect = mock_create
    return client


def generate_synthetic_batch(size: int = 65, seed: int = 42) -> List[Dict[str, Any]]:
    """
    Generates a deterministic, reproducible batch of 50-100 realistic synthetic payment failure events
    covering all root causes, multi-step recoveries, guardrail compliance blocks, LLM fallbacks, and escalations.
    """
    rng = random.Random(seed)
    events = []

    # Distribution configuration
    configs = [
        # 1. bank_timeout -> 1st action (smart_retry) success
        ("bank_timeout", 12, (2000, 15000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),
        # 2. bank_timeout -> 1st action fails, 2nd action (payment_link) success
        ("bank_timeout", 10, (5000, 25000), {0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),
        # 3. bank_timeout -> both fail -> playbook exhausted
        ("bank_timeout", 4, (3000, 12000), {0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.FAILED}, {"is_daytime": True}),
        # 4. bank_timeout -> night DND block on payment_link
        ("bank_timeout", 3, (4000, 20000), {0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.SUCCESS}, {"is_night": True}),
        # 5. bank_timeout -> large amount > 50,000 human approval block
        ("bank_timeout", 2, (55000, 85000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),

        # 6. nsf -> 1st action (delayed_retry) success
        ("nsf", 8, (1500, 8000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),
        # 7. nsf -> 1st action fails, 2nd action (payment_link) success
        ("nsf", 5, (2000, 10000), {0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),
        # 8. nsf -> both fail -> playbook exhausted
        ("nsf", 2, (1000, 5000), {0: ExecutionStatusEnum.FAILED, 1: ExecutionStatusEnum.FAILED}, {"is_daytime": True}),

        # 9. expired_card -> payment_link success
        ("expired_card", 5, (1000, 12000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),
        # 10. expired_card -> opted-out customer block
        ("expired_card", 2, (2000, 6000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True, "opted_out": True}),

        # 11. cart_abandonment -> discount_nudge success
        ("cart_abandonment", 3, (800, 4500), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),

        # 12. recent_overdue -> reminder success
        ("recent_overdue", 2, (3000, 18000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),

        # 13. chronic_non_payer -> immediate escalation
        ("chronic_non_payer", 2, (4000, 25000), {}, {"is_daytime": True}),

        # 14. retry_cap_exceeded -> attempt 5 block
        ("bank_timeout", 1, (3000, 8000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True, "attempt_number": 5}),

        # 15. Ambiguous signal -> LLM Fallback Success -> Recovery
        ("llm_ambiguous_success", 3, (4000, 14000), {0: ExecutionStatusEnum.SUCCESS}, {"is_daytime": True}),

        # 16. Ambiguous signal -> LLM Timeout Failure -> Safe Fallback to Unknown -> Escalation
        ("llm_timeout_failure", 1, (2500, 7500), {}, {"is_daytime": True}),
    ]

    ev_id_counter = 1000
    for rc_type, count, (amt_min, amt_max), sim_outcomes, ctx_info in configs:
        for _ in range(count):
            ev_id_counter += 1
            amount_inr = rng.randint(amt_min, amt_max)
            amount_paise = int(amount_inr * 100)
            customer_id = f"cust_{ev_id_counter}"

            if rc_type == "bank_timeout":
                error_code = "GATEWAY_ERROR"
                error_reason = "payment_timed_out"
                error_desc = "Bank server did not respond within timeout window."
            elif rc_type == "nsf":
                error_code = "BAD_REQUEST_ERROR"
                error_reason = "insufficient_funds"
                error_desc = "Insufficient funds in customer bank account."
            elif rc_type == "expired_card":
                error_code = "BAD_REQUEST_ERROR"
                error_reason = "card_expired"
                error_desc = "Card validity has expired."
            elif rc_type == "cart_abandonment":
                error_code = "CHECKOUT_DROPOFF"
                error_reason = "cart_abandoned"
                error_desc = "Customer dropped off at checkout."
            elif rc_type == "recent_overdue":
                error_code = "INVOICE_OVERDUE"
                error_reason = "invoice_overdue_1_day"
                error_desc = "Invoice payment overdue by 1 day."
            elif rc_type == "chronic_non_payer":
                error_code = "HIGH_RISK_USER"
                error_reason = "chronic_defaulter"
                error_desc = "Customer has chronic payment failure history."
            elif rc_type == "llm_ambiguous_success":
                error_code = "UNMAPPED_CUSTOM_GATEWAY_ERR"
                error_reason = "unrecognized_status"
                error_desc = "Card validity token has reached expiration on issuing bank."
            elif rc_type == "llm_timeout_failure":
                error_code = "SIMULATE_TIMEOUT_ERROR"
                error_reason = "unmapped_signal"
                error_desc = "SIMULATE_TIMEOUT in downstream partner authentication pipeline."
            else:
                error_code = "UNKNOWN"
                error_reason = "unknown"
                error_desc = "Unknown error"

            if ctx_info.get("is_night"):
                sim_dt = datetime(2026, 8, 27, 23, 15, 0)
            else:
                sim_dt = datetime(2026, 8, 27, 14, 0, 0)

            payload = {
                "entity": "event",
                "event": "payment.failed",
                "timestamp": sim_dt.isoformat(),
                "payload": {
                    "payment": {
                        "entity": {
                            "id": f"pay_syn_{ev_id_counter}",
                            "amount": amount_paise,
                            "currency": "INR",
                            "customer_id": customer_id,
                            "error_code": error_code,
                            "error_reason": error_reason,
                            "error_description": error_desc,
                            "created_at": int(sim_dt.timestamp()),
                        }
                    }
                },
                "_sim_outcomes": sim_outcomes,
                "_ctx_info": ctx_info,
            }
            events.append(payload)

    return events[:size]


def run_synthetic_batch(
    conn: sqlite3.Connection,
    batch: Optional[List[Dict[str, Any]]] = None,
    delay_between_events_s: float = 0.0,
    callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Executes a synthetic batch of events through the complete recovery pipeline,
    recording all database state transitions and append-only audit logs.
    """
    if batch is None:
        batch = generate_synthetic_batch(65)

    if llm_client is None:
        llm_client = create_deterministic_mock_llm_client()

    results = []
    for raw_event in batch:
        sim_outcomes = raw_event.get("_sim_outcomes", {})
        ctx_info = raw_event.get("_ctx_info", {})

        # Context construction
        if ctx_info.get("is_night"):
            current_time = datetime(2026, 8, 27, 23, 15, 0)
        else:
            current_time = datetime(2026, 8, 27, 14, 0, 0)

        guardrail_ctx = GuardrailContext(
            current_time=current_time,
            customer_opted_out=ctx_info.get("opted_out", False),
            attempt_number=ctx_info.get("attempt_number", 1),
        )

        # 1. Pipeline Ingestion & Detection & Tiered Diagnosis
        norm_ev, risk_ev, root_cause = process_payment_failed_event(
            raw_event=raw_event,
            conn=conn,
            use_llm_fallback=True,
            llm_client=llm_client,
        )

        # 2. Outcome Tracker Recovery Loop (Dispatches action; sets status IN_PROGRESS if action execution succeeds)
        wf_res = start_recovery_workflow(
            conn=conn,
            risk_id=risk_ev.risk_id,
            context=guardrail_ctx,
            simulated_action_outcomes=sim_outcomes,
            customer_id=norm_ev.customer_id,
        )

        final_status = wf_res.final_status.value
        amount_recovered = wf_res.amount_recovered

        # 3. For synthetic batch simulations where action execution succeeded (status IN_PROGRESS),
        # simulate customer payment completion via reconciliation engine
        if wf_res.final_status == EventStatus.IN_PROGRESS:
            from src.reconciliation import reconcile_payment_status
            recon_res = reconcile_payment_status(
                conn=conn,
                risk_id=risk_ev.risk_id,
                forced_status="RECOVERED",
                verification_source="synthetic_simulator",
                source_event="simulated_payment_confirmation",
            )
            final_status = EventStatus.RECOVERED.value
            amount_recovered = recon_res.get("amount_recovered", risk_ev.amount)

        event_summary = {
            "risk_id": risk_ev.risk_id,
            "event_id": norm_ev.event_id,
            "amount": risk_ev.amount,
            "root_cause": root_cause.root_cause.value,
            "source": root_cause.source,
            "status": final_status,
            "amount_recovered": amount_recovered,
            "reason": wf_res.reason,
        }
        results.append(event_summary)

        if callback:
            callback(event_summary)

        if delay_between_events_s > 0:
            time.sleep(delay_between_events_s)

    return {
        "total_processed": len(results),
        "events": results,
    }
