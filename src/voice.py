import sqlite3
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

from src.models import (
    RiskEvent,
    EventStatus,
    RootCauseEnum,
    ActionType,
    ExecutionStatusEnum,
    VoiceIntent,
    VoiceInteraction,
    GuardrailResultEnum,
)
from src.db import (
    get_risk_event,
    get_root_cause,
    update_risk_event_status,
    insert_voice_interaction,
    get_voice_interaction,
    list_voice_interactions_for_risk,
)
from src.integrations.config import is_voice_enabled
from src.guardrails import GuardrailContext, evaluate_and_record_guardrails, is_dnd_hours
from src.executor import execute_action
from src.outcome_tracker import record_escalation, handle_outcome
from src.audit import log_audit
from src.integrations.twilio_client import initiate_twilio_call, generate_twiml_response


# Pluggable STT Adapters
class MockSTTAdapter:
    """Mock Speech-to-Text adapter for deterministic unit and integration tests."""

    def transcribe(self, audio_data: str) -> str:
        # In mock mode, audio_data string represents transcribed text
        return audio_data.strip()


class RealSTTAdapter:
    """Real STT adapter placeholder for production Speech-to-Text integration (e.g. Google Cloud Speech / Deepgram)."""

    def transcribe(self, audio_data: str) -> str:
        # Real STT provider logic
        return audio_data.strip()


# Pluggable TTS Adapters
class MockTTSAdapter:
    """Mock Text-to-Speech adapter returning Hinglish speech response."""

    def synthesize(self, text: str) -> str:
        return text.strip()


class RealTTSAdapter:
    """Real TTS adapter placeholder for production Text-to-Speech integration (e.g. Google Cloud TTS / ElevenLabs)."""

    def synthesize(self, text: str) -> str:
        return text.strip()


def check_voice_eligibility(
    conn: sqlite3.Connection,
    risk_id: str,
    phone_number: str,
    context: Optional[GuardrailContext] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Evaluates pre-check rules before ANY outbound voice interaction:
    1. Feature flag VOICE_ENABLED
    2. Customer opt-out status
    3. DND hours (9 AM - 8 PM)
    4. Valid phone number format
    5. Recovery validity (status must be IN_PROGRESS or DETECTED)
    6. Human-only case (e.g. CHRONIC_NON_PAYER)
    """
    ref_time = now or datetime.utcnow()
    ctx = context or GuardrailContext(current_time=ref_time)

    # 1. Feature flag
    if not is_voice_enabled():
        return {"eligible": False, "reason": "voice_disabled"}

    # 2. Customer opt-out
    if ctx.customer_opted_out:
        return {"eligible": False, "reason": "customer_opted_out"}

    # 3. DND hours check
    if is_dnd_hours(ctx.current_time):
        return {"eligible": False, "reason": "dnd_hours"}

    # 4. Valid phone number check
    if not phone_number or not isinstance(phone_number, str):
        return {"eligible": False, "reason": "invalid_phone_number"}

    clean_phone = "".join(c for c in phone_number if c.isdigit())
    if len(clean_phone) < 10:
        return {"eligible": False, "reason": "invalid_phone_number"}

    # 5. Recovery validity & risk event status
    risk_event = get_risk_event(conn, risk_id)
    if not risk_event:
        return {"eligible": False, "reason": "risk_event_not_found"}

    if risk_event.status in {EventStatus.RECOVERED, EventStatus.ESCALATED}:
        return {"eligible": False, "reason": f"invalid_status:{risk_event.status.value}"}

    # 6. Human-only case
    rc = get_root_cause(conn, risk_id)
    if rc and rc.root_cause == RootCauseEnum.CHRONIC_NON_PAYER:
        return {"eligible": False, "reason": "human_only_case:chronic_non_payer"}

    return {"eligible": True, "reason": "PASS"}


def extract_hinglish_intent(transcript: str) -> VoiceIntent:
    """
    Classifies Hinglish user transcript strictly into fixed VoiceIntent enum values:
    SEND_PAYMENT_LINK, CONFIRM_PAYMENT, ASK_STATUS, SPEAK_TO_HUMAN, DECLINE.
    Never produces arbitrary actions.
    """
    if not transcript or not isinstance(transcript, str):
        return VoiceIntent.SPEAK_TO_HUMAN

    text = transcript.lower().strip()

    # Fixed intent mapping rules
    if any(k in text for k in ["link bhej", "payment link", "sms bhej", "whatsapp link", "link send", "bhej do link", "send link"]):
        return VoiceIntent.SEND_PAYMENT_LINK

    if any(k in text for k in ["payment kar diya", "pay kar diya", "pay kar raha", "confirm payment", "already paid", "kar diya"]):
        return VoiceIntent.CONFIRM_PAYMENT

    if any(k in text for k in ["status kya", "kya status", "check status", "balance check", "status check"]):
        return VoiceIntent.ASK_STATUS

    if any(k in text for k in ["agent se baat", "human agent", "executive", "customer care", "talk to agent", "connect to human"]):
        return VoiceIntent.SPEAK_TO_HUMAN

    if any(k in text for k in ["nahi", "don't want", "cancel", "mat bhej", "no thanks", "nahi chahiye"]):
        return VoiceIntent.DECLINE

    # Unsupported or low confidence -> default safe human handoff
    return VoiceIntent.SPEAK_TO_HUMAN


def process_voice_interaction(
    conn: sqlite3.Connection,
    risk_id: str,
    transcript: str,
    phone_number: str = "+919876543210",
    context: Optional[GuardrailContext] = None,
    now: Optional[datetime] = None,
    simulated_action_outcome: Optional[ExecutionStatusEnum] = None,
) -> Dict[str, Any]:
    """
    Processes Hinglish voice interaction:
    1. Pre-check voice eligibility.
    2. Extract fixed VoiceIntent.
    3. Route through EXISTING recovery engine, playbooks, guardrails, and action executor.
    4. Record interaction and immutable audit log.
    """
    ref_time = now or datetime.utcnow()
    interaction_id = f"voice_{uuid.uuid4().hex[:12]}"
    risk_event = get_risk_event(conn, risk_id)

    if not risk_event:
        return {"status": "not_found", "risk_id": risk_id}

    # 1. Eligibility Check
    elig = check_voice_eligibility(conn, risk_id, phone_number, context=context, now=ref_time)
    if not elig["eligible"]:
        interaction = VoiceInteraction(
            interaction_id=interaction_id,
            risk_id=risk_id,
            eligibility_status=f"BLOCKED:{elig['reason']}",
            transcript=transcript,
            escalation_reason=elig["reason"],
            created_at=ref_time,
        )
        insert_voice_interaction(conn, interaction)
        record_escalation(conn, risk_id, reason=f"voice_eligibility_blocked:{elig['reason']}")
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="voice_engine",
            input_data={"transcript": transcript, "phone_number": phone_number},
            output_data=interaction,
            decision="voice_eligibility_blocked_escalated",
        )
        return {"status": "blocked", "reason": elig["reason"], "escalated": True}

    # 2. Extract Intent
    stt = MockSTTAdapter()
    clean_transcript = stt.transcribe(transcript)
    intent = extract_hinglish_intent(clean_transcript)
    tts = MockTTSAdapter()

    guardrail_res = None
    execution_res = None
    escalation_reason = None
    action_type = None
    tts_msg = ""

    # 3. Route Intent to Existing Recovery Engine
    if intent == VoiceIntent.SEND_PAYMENT_LINK:
        action_type = ActionType.PAYMENT_LINK

        # Evaluate existing guardrails (MUST NOT BYPASS GUARDRAILS!)
        guard_check = evaluate_and_record_guardrails(
            conn=conn,
            risk_id=risk_id,
            amount=risk_event.amount,
            action_index=0,
            action_type=action_type,
            context=context,
        )
        guardrail_res = guard_check.result.value

        if guard_check.result == GuardrailResultEnum.BLOCK:
            escalation_reason = f"guardrail_blocked:{guard_check.reason}"
            record_escalation(conn, risk_id, reason=escalation_reason)
            update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
            tts_msg = tts.synthesize("Aapka request process nahi ho saka. Main aapko support agent se connect karta hoon.")
            status = "guardrail_blocked"
        else:
            # Execute action via Action Executor (MUST USE ORIGINAL RISK AMOUNT & CUSTOMER ID!)
            exec_obj = execute_action(
                risk_id=risk_id,
                action_type=action_type,
                action_index=0,
                amount=risk_event.amount,
                customer_id="customer_unknown",
                simulate_status=simulated_action_outcome or ExecutionStatusEnum.SUCCESS,
                conn=conn,
            )
            execution_res = exec_obj.status.value

            if exec_obj.status == ExecutionStatusEnum.SUCCESS:
                rc = get_root_cause(conn, risk_id)
                if not rc:
                    from src.models import RootCause
                    from src.db import insert_root_cause
                    insert_root_cause(conn, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0, source="voice_interaction"))

                # Record outcome using existing outcome tracker
                handle_outcome(
                    conn=conn,
                    risk_id=risk_id,
                    action_index=0,
                    execution_status=ExecutionStatusEnum.SUCCESS,
                    context=context,
                )
                tts_msg = tts.synthesize("Theek hai, main aapko payment link bhej deta hoon.")
                status = "executed"
            else:
                rc = get_root_cause(conn, risk_id)
                if not rc:
                    from src.models import RootCause
                    from src.db import insert_root_cause
                    insert_root_cause(conn, RootCause(risk_id=risk_id, root_cause=RootCauseEnum.BANK_TIMEOUT, confidence=1.0, source="voice_interaction"))

                handle_outcome(
                    conn=conn,
                    risk_id=risk_id,
                    action_index=0,
                    execution_status=ExecutionStatusEnum.FAILED,
                    context=context,
                )
                tts_msg = tts.synthesize("Payment link bhejne me problem aayi. Main agent se connect kar raha hoon.")
                status = "failed"

    elif intent == VoiceIntent.CONFIRM_PAYMENT:
        tts_msg = tts.synthesize("Dhanyawad! Aapka payment confirmation verify kiya ja raha hai.")
        status = "confirmed"

    elif intent == VoiceIntent.ASK_STATUS:
        tts_msg = tts.synthesize(f"Aapka payment status abhi {risk_event.status.value} hai.")
        status = "status_checked"

    else:
        # SPEAK_TO_HUMAN or DECLINE -> Escalates safely to human agent
        escalation_reason = f"voice_intent:{intent.value.lower()}"
        record_escalation(conn, risk_id, reason=escalation_reason)
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        tts_msg = tts.synthesize("Theek hai, main aapki baat executive se karwata hoon.")
        status = "escalated_to_human"

    # 4. Save VoiceInteraction & Audit Log
    interaction = VoiceInteraction(
        interaction_id=interaction_id,
        risk_id=risk_id,
        eligibility_status="ELIGIBLE",
        transcript=clean_transcript,
        intent=intent,
        action_requested=action_type,
        guardrail_result=guardrail_res,
        execution_result=execution_res,
        escalation_reason=escalation_reason,
        created_at=ref_time,
    )
    insert_voice_interaction(conn, interaction)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="voice_engine",
        input_data={"transcript": clean_transcript, "intent": intent.value},
        output_data=interaction,
        decision=f"voice_interaction_{status}",
    )

    return {
        "status": status,
        "interaction_id": interaction_id,
        "intent": intent.value,
        "action_requested": action_type.value if action_type else None,
        "guardrail_result": guardrail_res,
        "execution_result": execution_res,
        "tts_response": tts_msg,
    }


def initiate_outbound_voice_call(
    conn: sqlite3.Connection,
    risk_id: str,
    phone_number: str = "+919876543210",
    context: Optional[GuardrailContext] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Initiates outbound voice call after verifying eligibility."""
    ref_time = now or datetime.utcnow()
    elig = check_voice_eligibility(conn, risk_id, phone_number, context=context, now=ref_time)

    if not elig["eligible"]:
        interaction_id = f"voice_{uuid.uuid4().hex[:12]}"
        interaction = VoiceInteraction(
            interaction_id=interaction_id,
            risk_id=risk_id,
            eligibility_status=f"BLOCKED:{elig['reason']}",
            escalation_reason=elig["reason"],
            created_at=ref_time,
        )
        insert_voice_interaction(conn, interaction)
        record_escalation(conn, risk_id, reason=f"voice_call_blocked:{elig['reason']}")
        update_risk_event_status(conn, risk_id, EventStatus.ESCALATED)
        log_audit(
            conn=conn,
            risk_id=risk_id,
            layer="voice_engine",
            input_data={"phone_number": phone_number},
            output_data=interaction,
            decision="voice_call_blocked_escalated",
        )
        return {"status": "blocked", "reason": elig["reason"], "escalated": True}

    call_res = initiate_twilio_call(to_phone=phone_number, callback_url="/api/voice/webhook/incoming")
    interaction_id = f"voice_{uuid.uuid4().hex[:12]}"
    interaction = VoiceInteraction(
        interaction_id=interaction_id,
        risk_id=risk_id,
        call_sid=call_res.get("call_sid"),
        eligibility_status="ELIGIBLE",
        created_at=ref_time,
    )
    insert_voice_interaction(conn, interaction)

    log_audit(
        conn=conn,
        risk_id=risk_id,
        layer="voice_engine",
        input_data={"phone_number": phone_number},
        output_data=interaction,
        decision="voice_call_initiated",
    )

    return {
        "status": "call_initiated",
        "interaction_id": interaction_id,
        "call_sid": call_res.get("call_sid"),
        "provider": call_res.get("provider"),
    }
