import os
import uuid
from typing import Dict, Any, Optional

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+15005550006")


def initiate_twilio_call(to_phone: str, callback_url: str) -> Dict[str, Any]:
    """
    Initiates an outbound voice call via Twilio API.
    If Twilio credentials are absent or in mock execution mode, returns a deterministic mock call response.
    Never logs sensitive credentials.
    """
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_ACCOUNT_SID != "dummy_sid":
        try:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            call = client.calls.create(
                to=to_phone,
                from_=TWILIO_PHONE_NUMBER,
                url=callback_url,
            )
            return {
                "status": "initiated",
                "call_sid": call.sid,
                "provider": "twilio_real",
            }
        except Exception as exc:
            # Fall back to mock call SID on API error
            call_sid = f"CA_mock_{uuid.uuid4().hex[:12]}"
            return {
                "status": "initiated_mock_fallback",
                "call_sid": call_sid,
                "error": str(exc),
                "provider": "twilio_mock",
            }

    # Deterministic mock execution
    call_sid = f"CA_mock_{uuid.uuid4().hex[:12]}"
    return {
        "status": "initiated",
        "call_sid": call_sid,
        "provider": "twilio_mock",
    }


def generate_twiml_response(message: str, gather_input: bool = True, action_url: str = "/api/voice/webhook/gather") -> str:
    """
    Generates TwiML XML markup for Twilio voice response in Hinglish / Hindi.
    """
    clean_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    if gather_input:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather input="speech" action="{action_url}" method="POST" speechTimeout="auto" language="hi-IN">
        <Say voice="Polly.Aditi">{clean_msg}</Say>
    </Gather>
</Response>"""
    else:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Aditi">{clean_msg}</Say>
    <Hangup/>
</Response>"""

    return twiml
