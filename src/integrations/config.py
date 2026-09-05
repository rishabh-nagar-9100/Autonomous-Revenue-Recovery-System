import os
from enum import Enum
from typing import Dict, Any


class ExecutionMode(str, Enum):
    MOCK = "mock"
    SANDBOX = "sandbox"


# Load .env file from project root if present
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k, _v = _k.strip(), _v.strip().strip("'\"")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass


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


# Razorpay API Credentials (read dynamically with fallback to env/defaults)
def get_razorpay_key_id() -> str:
    return os.getenv("RAZORPAY_KEY_ID", "rzp_test_dummy_key_id")

def get_razorpay_key_secret() -> str:
    return os.getenv("RAZORPAY_KEY_SECRET", "dummy_secret_key")

def get_razorpay_webhook_secret() -> str:
    return os.getenv("RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret")

RAZORPAY_KEY_ID = get_razorpay_key_id()
RAZORPAY_KEY_SECRET = get_razorpay_key_secret()
RAZORPAY_WEBHOOK_SECRET = get_razorpay_webhook_secret()

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
        "b2b_enabled": is_b2b_enabled(),
        "info_gathering_enabled": is_info_gathering_enabled(),
        "voice_enabled": is_voice_enabled(),
        "fault_injection_enabled": get_env_bool("FAULT_INJECTION_ENABLED", False),
        "demo_fallback_to_mock": get_env_bool("DEMO_FALLBACK_TO_MOCK", False),
        "info_recovery_window_days": int(os.getenv("INFO_RECOVERY_WINDOW_DAYS", "7")),
        "max_reconciliation_attempts": int(os.getenv("MAX_RECONCILIATION_ATTEMPTS", "3")),
        "max_reconciliation_hours": int(os.getenv("MAX_RECONCILIATION_HOURS", "24")),
    }
