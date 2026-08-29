import os
import json
import logging
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field, ValidationError
from src.models import NormalizedEvent, RiskEvent, RootCauseEnum, ActionType


logger = logging.getLogger(__name__)

ALLOWED_ROOT_CAUSES = {rc.value for rc in RootCauseEnum}

DEFAULT_MODEL = "claude-3-haiku-20240307"


class LLMRootCauseResponse(BaseModel):
    root_cause: RootCauseEnum
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


def get_anthropic_client(client: Optional[Any] = None) -> Optional[Any]:
    """
    Returns an Anthropic client instance if available, or None if ANTHROPIC_API_KEY is unset.
    """
    if client is not None:
        return client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    except Exception as e:
        logger.warning(f"Failed to initialize Anthropic client: {e}")
        return None


def diagnose_root_cause_llm(
    event: NormalizedEvent,
    risk_event: RiskEvent,
    client: Optional[Any] = None,
    timeout: float = 3.0,
    model: str = DEFAULT_MODEL,
) -> Optional[LLMRootCauseResponse]:
    """
    Tier 2 LLM Fallback for ambiguous or unmapped payment failures.
    Strictly validates structured output into fixed RootCauseEnum.
    Returns None on any error, timeout, malformed output, or invalid enum.
    """
    ai_client = get_anthropic_client(client)
    if ai_client is None:
        return None

    prompt = f"""You are a specialized financial risk diagnosis engine.
Analyze the following payment failure event and classify it into EXACTLY ONE root cause category.

Transaction Data:
- Event ID: {event.event_id}
- Amount: ₹{event.amount} {event.currency}
- Customer ID: {event.customer_id}
- Error Code: {event.error_code or 'None'}
- Error Reason: {event.error_reason or 'None'}
- Error Description: {event.error_description or 'None'}
- Metadata: {json.dumps(event.metadata)}

Allowed Categories (choose strictly one):
- bank_timeout
- nsf
- expired_card
- cart_abandonment
- recent_overdue
- chronic_non_payer
- unknown

Respond ONLY with valid JSON in this exact structure:
{{
  "root_cause": "<category>",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<short concise reason>"
}}"""

    try:
        response = ai_client.messages.create(
            model=model,
            max_tokens=250,
            timeout=timeout,
            system="You are a strict financial API classifier. Output valid raw JSON only.",
            messages=[{"role": "user", "content": prompt}],
        )

        content_text = ""
        if hasattr(response, "content") and response.content:
            for block in response.content:
                if hasattr(block, "text"):
                    content_text += block.text
                elif isinstance(block, dict) and "text" in block:
                    content_text += block["text"]

        content_text = content_text.strip()
        # Handle markdown codeblock formatting if present
        if content_text.startswith("```json"):
            content_text = content_text[7:]
        if content_text.startswith("```"):
            content_text = content_text[3:]
        if content_text.endswith("```"):
            content_text = content_text[:-3]
        content_text = content_text.strip()

        data = json.loads(content_text)
        if not isinstance(data, dict):
            return None

        rc_val = str(data.get("root_cause", "")).strip().lower()
        if rc_val not in ALLOWED_ROOT_CAUSES:
            logger.warning(f"LLM returned invalid root_cause enum: {rc_val}")
            return None

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(data.get("reasoning", "LLM classified"))

        return LLMRootCauseResponse(
            root_cause=RootCauseEnum(rc_val),
            confidence=confidence,
            reasoning=reasoning,
        )
    except Exception as e:
        logger.warning(f"LLM root-cause diagnosis failed or timed out: {e}")
        return None


def get_deterministic_message_fallback(
    action_type: ActionType,
    amount: float,
    customer_id: str,
) -> str:
    """Provides high-quality deterministic template fallbacks for customer communications."""
    if action_type == ActionType.PAYMENT_LINK:
        return f"Hi! Your transaction of ₹{amount:,.2f} could not be completed. Please use this secure link to complete your payment: https://rzp.io/i/plink"
    elif action_type == ActionType.REMINDER:
        return f"Friendly reminder: Your payment of ₹{amount:,.2f} is pending. Please complete your transaction to avoid service interruption."
    elif action_type == ActionType.DISCOUNT_NUDGE:
        return f"We noticed you left items in your cart! Complete your checkout for ₹{amount:,.2f} now and enjoy an exclusive discount."
    elif action_type == ActionType.SMART_RETRY:
        return f"Your payment of ₹{amount:,.2f} is being re-processed with your bank."
    elif action_type == ActionType.DELAYED_RETRY:
        return f"We will re-attempt your payment of ₹{amount:,.2f} shortly."
    return f"Update on your transaction of ₹{amount:,.2f}."


def draft_action_message_llm(
    risk_id: str,
    action_type: ActionType,
    amount: float,
    customer_id: str,
    root_cause: RootCauseEnum,
    client: Optional[Any] = None,
    timeout: float = 3.0,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Drafts a personalized, professional customer-facing message for the FIRST recovery action only.
    Strictly wrapped with fallback to deterministic templates on any failure.
    """
    fallback_msg = get_deterministic_message_fallback(action_type, amount, customer_id)

    ai_client = get_anthropic_client(client)
    if ai_client is None:
        return fallback_msg

    prompt = f"""Draft a short, professional, and empathetic SMS/WhatsApp notification to a customer regarding their payment.

Context:
- Action Type: {action_type.value}
- Amount: ₹{amount:,.2f}
- Customer ID: {customer_id}
- Root Cause: {root_cause.value}

Constraints:
1. Max 2 sentences, clear and courteous.
2. DO NOT mention internal error codes, internal system architecture, or tech jargon.
3. DO NOT promise guaranteed payment success or claim bank liability.
4. If payment_link, mention using the provided secure link.
5. If discount_nudge, invite them to complete checkout.
6. Output ONLY the message text without quotes or preamble."""

    try:
        response = ai_client.messages.create(
            model=model,
            max_tokens=150,
            timeout=timeout,
            system="You are a professional customer success copywriter for financial notifications. Return clean message text only.",
            messages=[{"role": "user", "content": prompt}],
        )

        content_text = ""
        if hasattr(response, "content") and response.content:
            for block in response.content:
                if hasattr(block, "text"):
                    content_text += block.text
                elif isinstance(block, dict) and "text" in block:
                    content_text += block["text"]

        clean_text = content_text.strip().strip('"').strip("'")
        if len(clean_text) > 10:
            return clean_text
        return fallback_msg
    except Exception as e:
        logger.warning(f"LLM message drafting failed or timed out: {e}")
        return fallback_msg
