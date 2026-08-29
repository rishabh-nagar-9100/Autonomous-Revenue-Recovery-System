import os
import random
from typing import Optional, Dict, Any
from dataclasses import dataclass
from src.integrations.config import FAULT_INJECTION_ENABLED


class FaultInjectionError(Exception):
    """Base exception raised when a fault is injected in test mode."""
    pass


class NetworkTimeoutFaultError(FaultInjectionError):
    pass


class Transient5xxFaultError(FaultInjectionError):
    pass


class ConnectionResetFaultError(FaultInjectionError):
    pass


@dataclass
class FaultConfig:
    fault_type: str  # network_timeout, transient_5xx, duplicate_webhook, out_of_order_webhook, duplicate_success, late_success, connection_reset
    probability: float = 1.0
    delay_ms: int = 0


# Global test configuration for fault injection
_ACTIVE_FAULTS: Dict[str, FaultConfig] = {}


def set_fault_config(target_key: str, fault_config: Optional[FaultConfig]) -> None:
    """Configures a test fault for a specific target key (e.g. action type or webhook event)."""
    global _ACTIVE_FAULTS
    if fault_config is None:
        _ACTIVE_FAULTS.pop(target_key, None)
    else:
        _ACTIVE_FAULTS[target_key] = fault_config


def clear_all_faults() -> None:
    """Clears all registered test faults."""
    global _ACTIVE_FAULTS
    _ACTIVE_FAULTS.clear()


def inject_fault_if_configured(target_key: str) -> None:
    """
    Checks if fault injection is enabled and if a fault is configured for the target key.
    If so, injects the corresponding fault (raises exception or applies delay).
    """
    if not FAULT_INJECTION_ENABLED and not os.getenv("FAULT_INJECTION_ENABLED", "").lower() in {"true", "1"}:
        return

    fault = _ACTIVE_FAULTS.get(target_key)
    if not fault:
        return

    if random.random() <= fault.probability:
        if fault.delay_ms > 0:
            import time
            time.sleep(fault.delay_ms / 1000.0)

        if fault.fault_type == "network_timeout":
            raise NetworkTimeoutFaultError(f"[INJECTED FAULT] Network timeout simulating uncertain response for {target_key}")
        elif fault.fault_type == "transient_5xx":
            raise Transient5xxFaultError(f"[INJECTED FAULT] Transient HTTP 503 Service Unavailable for {target_key}")
        elif fault.fault_type == "connection_reset":
            raise ConnectionResetFaultError(f"[INJECTED FAULT] Connection reset by peer for {target_key}")
