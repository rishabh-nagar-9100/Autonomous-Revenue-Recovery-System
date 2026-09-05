import os
import pytest
import src.integrations.config as config_mod

@pytest.fixture(autouse=True)
def reset_test_environment(monkeypatch):
    """
    Ensures unit tests run in deterministic mock execution mode with test defaults,
    preventing unintended external API calls or environment contamination during automated testing.
    """
    monkeypatch.setenv("EXECUTION_MODE", "mock")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_dummy_key_id")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "dummy_secret_key")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret")
    monkeypatch.setenv("B2B_ENABLED", "false")
    monkeypatch.setenv("INFO_GATHERING_ENABLED", "false")
    monkeypatch.setenv("VOICE_ENABLED", "false")
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "false")
    monkeypatch.setenv("DEMO_FALLBACK_TO_MOCK", "false")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Keep module constants in sync during tests
    monkeypatch.setattr(config_mod, "RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret")
    monkeypatch.setattr(config_mod, "RAZORPAY_KEY_ID", "rzp_test_dummy_key_id")
    monkeypatch.setattr(config_mod, "RAZORPAY_KEY_SECRET", "dummy_secret_key")
