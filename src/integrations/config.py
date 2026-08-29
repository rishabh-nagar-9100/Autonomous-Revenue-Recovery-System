import os
from enum import Enum
from typing import Dict, Any


class ExecutionMode(str, Enum):
    MOCK = "mock"
    SANDBOX = "sandbox"


def get_env_bool(var_name: str, default: bool = False) -> bool:
    """Helper to parse boolean values from environment variables."""
    val = os.getenv(var_name, "").strip().lower()
    if val in {"true", "1", "yes", "on"}:
        return True
    if val in {"false", "0", "no", "off"}:
        return False
    return default


def get_execution_mode() -> ExecutionMode:
    """Returns the currently configured ExecutionMode (mock or sandbox)."""
    mode_str = os.getenv("EXECUTION_MODE", "mock").strip().lower()
    if mode_str == "sandbox":
        return ExecutionMode.SANDBOX
    return ExecutionMode.MOCK


# Razorpay API Credentials
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_dummy_key_id")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "dummy_secret_key")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret")

# Post-MVP Feature Flags (Default to safe mock/false values)
B2B_ENABLED = get_env_bool("B2B_ENABLED", False)
INFO_GATHERING_ENABLED = get_env_bool("INFO_GATHERING_ENABLED", False)
VOICE_ENABLED = get_env_bool("VOICE_ENABLED", False)
FAULT_INJECTION_ENABLED = get_env_bool("FAULT_INJECTION_ENABLED", False)
DEMO_FALLBACK_TO_MOCK = get_env_bool("DEMO_FALLBACK_TO_MOCK", False)


def is_b2b_enabled() -> bool:
    """Returns True if B2B Receivables Recovery is dynamically enabled via environment."""
    return get_env_bool("B2B_ENABLED", False)


def is_info_gathering_enabled() -> bool:
    """Returns True if Information Gathering is dynamically enabled via environment."""
    return get_env_bool("INFO_GATHERING_ENABLED", False)


def is_voice_enabled() -> bool:
    """Returns True if Hinglish Voice Recovery is dynamically enabled via environment."""
    return get_env_bool("VOICE_ENABLED", False)

# Configurable Operational Invariants & Thresholds
INFO_RECOVERY_WINDOW_DAYS = int(os.getenv("INFO_RECOVERY_WINDOW_DAYS", "7"))
MAX_RECONCILIATION_ATTEMPTS = int(os.getenv("MAX_RECONCILIATION_ATTEMPTS", "3"))
MAX_RECONCILIATION_HOURS = int(os.getenv("MAX_RECONCILIATION_HOURS", "24"))


def get_feature_flags_status() -> Dict[str, Any]:
    """Returns a dictionary summary of all active feature flags and execution config."""
    return {
        "execution_mode": get_execution_mode().value,
        "b2b_enabled": B2B_ENABLED,
        "info_gathering_enabled": INFO_GATHERING_ENABLED,
        "voice_enabled": VOICE_ENABLED,
        "fault_injection_enabled": FAULT_INJECTION_ENABLED,
        "demo_fallback_to_mock": DEMO_FALLBACK_TO_MOCK,
        "info_recovery_window_days": INFO_RECOVERY_WINDOW_DAYS,
        "max_reconciliation_attempts": MAX_RECONCILIATION_ATTEMPTS,
        "max_reconciliation_hours": MAX_RECONCILIATION_HOURS,
    }
