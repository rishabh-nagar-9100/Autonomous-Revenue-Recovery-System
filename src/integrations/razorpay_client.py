import hmac
import hashlib
from typing import Dict, Any, Optional
import razorpay
from razorpay.errors import (
    BadRequestError,
    GatewayError,
    ServerError,
    SignatureVerificationError,
)
from src.integrations.config import (
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET,
    get_razorpay_key_id,
    get_razorpay_key_secret,
    get_razorpay_webhook_secret,
)


class RazorpayClientAdapter:
    """
    Thin SDK wrapper around the official Razorpay Python Client.
    Exposes narrow payment link, query, and verification methods without leaking raw client objects.
    """

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ):
        self.key_id = key_id or get_razorpay_key_id()
        self.key_secret = key_secret or get_razorpay_key_secret()
        self.webhook_secret = webhook_secret or get_razorpay_webhook_secret()
        self._client = razorpay.Client(auth=(self.key_id, self.key_secret))

    def create_payment_link(
        self,
        amount: float,
        customer_id: str,
        description: str = "Revenue Recovery Payment Link",
        reference_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a Razorpay Payment Link via the Payment Link API.
        Amount is passed in float INR rupees and converted to paise for Razorpay.
        """
        amount_in_paise = int(round(amount * 100))
        payload = {
            "amount": amount_in_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": description,
            "customer": {
                "name": f"Customer_{customer_id}",
                "contact": "+919876543210",
                "email": f"{customer_id}@example.com" if "@" not in customer_id else customer_id,
            },
            "notify": {"sms": True, "email": True},
            "reminder_enable": True,
            "notes": {
                "customer_id": customer_id,
                "system": "AI_Revenue_Recovery",
                "reference_id": reference_id or "",
            },
        }
        if reference_id:
            payload["reference_id"] = reference_id

        try:
            response = self._client.payment_link.create(data=payload)
            return {
                "payment_link_id": response.get("id"),
                "short_url": response.get("short_url"),
                "status": response.get("status"),
                "amount": amount,
                "currency": "INR",
                "raw_response": response,
            }
        except (BadRequestError, GatewayError, ServerError, SignatureVerificationError, Exception) as err:
            raise RuntimeError(f"Razorpay Payment Link creation failed: {str(err)}") from err

    def fetch_payment_link(self, payment_link_id: str) -> Dict[str, Any]:
        """Fetches payment link details by payment link ID."""
        try:
            return self._client.payment_link.fetch(payment_link_id)
        except (BadRequestError, GatewayError, ServerError, SignatureVerificationError, Exception) as err:
            raise RuntimeError(f"Razorpay fetch payment link failed for ID {payment_link_id}: {str(err)}") from err

    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        """Fetches payment details by payment ID."""
        try:
            return self._client.payment.fetch(payment_id)
        except (BadRequestError, GatewayError, ServerError, SignatureVerificationError, Exception) as err:
            raise RuntimeError(f"Razorpay fetch payment failed for ID {payment_id}: {str(err)}") from err

    def fetch_order(self, order_id: str) -> Dict[str, Any]:
        """Fetches order details by order ID."""
        try:
            return self._client.order.fetch(order_id)
        except (BadRequestError, GatewayError, ServerError, SignatureVerificationError, Exception) as err:
            raise RuntimeError(f"Razorpay fetch order failed for ID {order_id}: {str(err)}") from err

    def verify_payment_signature(
        self,
        order_id: str,
        payment_id: str,
        signature: str,
    ) -> bool:
        """Verifies payment signature using Razorpay utility."""
        params = {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        }
        try:
            self._client.utility.verify_payment_signature(params)
            return True
        except SignatureVerificationError:
            return False

    def verify_webhook_signature(
        self,
        raw_body: str,
        signature: str,
        webhook_secret: Optional[str] = None,
    ) -> bool:
        """
        Verifies Razorpay webhook signature using HMAC-SHA256.
        """
        secret = webhook_secret or self.webhook_secret
        if not secret or not signature or not raw_body:
            return False

        try:
            # Official SDK utility attempt first if available
            self._client.utility.verify_webhook_signature(
                body=raw_body,
                signature=signature,
                secret=secret,
            )
            return True
        except Exception:
            # Direct HMAC-SHA256 fallback computation
            expected_signature = hmac.new(
                key=secret.encode("utf-8"),
                msg=raw_body.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected_signature.lower(), signature.lower())
