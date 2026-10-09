"""
Phase 8: Testing Levels Verification Suite.

This module provides explicit, demonstrative automated test cases for each of
the four standard software testing levels in the Autonomous Revenue Recovery System:
1. Unit Testing: Function isolation (no I/O, no DB, pure business logic).
2. Integration Testing: Inter-module coordination and state persistence across DB and guardrails.
3. System Testing: Full application execution through external-facing FastAPI HTTP endpoints.
4. Acceptance Testing: Regulatory compliance, financial invariants, and non-negotiable safety rules.
"""

import sqlite3
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from src.models import (
    NormalizedEvent,
    RiskEvent,
    RiskType,
    Priority,
    EventStatus,
    ActionType,
    GuardrailResultEnum,
    Execution,
    ExecutionStatusEnum,
)
from src.risk_detector import detect_revenue_risk
from src.guardrails import (
    GuardrailContext,
    evaluate_and_record_guardrails,
)
from src.db import (
    init_db,
    insert_risk_event,
    get_guardrail_check,
    get_risk_event,
    insert_execution,
)
from src.server import app


# ==============================================================================
# LEVEL 1: UNIT TESTING
# ==============================================================================
def test_level_1_unit_pure_function_isolation():
    """
    [UNIT TESTING]
    Objective: Test a single business logic function in complete isolation
    without I/O, database dependencies, network calls, or downstream components.
    
    Verifies that detect_revenue_risk correctly applies the risk heuristic:
    Amount=3000.0 (>=2500.0 and <10000.0) produces Priority.MEDIUM risk event.
    """
    event = NormalizedEvent(
        event_id="evt_unit_lvl1_001",
        event_type="payment_failed",
        amount=3000.0,
        currency="INR",
        timestamp=datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc),
        customer_id="cust_unit_001",
        metadata={"customer_tier": "standard"},
    )
    
    risk = detect_revenue_risk(event)
    
    assert risk.risk_id == "risk_evt_unit_lvl1_001"
    assert risk.risk_type == RiskType.PAYMENT_FAILED
    assert risk.priority == Priority.MEDIUM
    assert risk.amount == 3000.0
    assert risk.status == EventStatus.DETECTED


# ==============================================================================
# LEVEL 2: INTEGRATION TESTING
# ==============================================================================
def test_level_2_integration_guardrails_persistence():
    """
    [INTEGRATION TESTING]
    Objective: Verify interaction between multiple application components:
    Decision Engine / Guardrails -> SQLite Database -> Retrieval Layer.
    
    Verifies that evaluate_and_record_guardrails performs rule validation
    and commits a persistent GuardrailCheck row into the SQLite database.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    
    try:
        # Arrange test case
        risk = RiskEvent(
            risk_id="risk_integ_lvl2_001",
            event_id="evt_integ_lvl2_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=80000.0,
            priority=Priority.HIGH,
            status=EventStatus.DETECTED,
            created_at=datetime(2026, 10, 8, 14, 0, 0, tzinfo=timezone.utc),
        )
        insert_risk_event(conn, risk)
        
        ctx = GuardrailContext(
            current_time=datetime(2026, 10, 8, 14, 0, 0, tzinfo=timezone.utc),
            human_approval_threshold=50000.0,
        )
        
        # Act: Execute guardrail evaluation across components
        check = evaluate_and_record_guardrails(
            conn=conn,
            risk_id="risk_integ_lvl2_001",
            amount=80000.0,
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            context=ctx,
        )
        
        # Assert: Guardrail result
        assert check.result == GuardrailResultEnum.BLOCK
        assert check.reason == "amount_requires_human_approval"
        
        # Assert: Cross-component database persistence
        retrieved = get_guardrail_check(conn, "risk_integ_lvl2_001", 0)
        assert retrieved is not None
        assert retrieved.risk_id == "risk_integ_lvl2_001"
        assert retrieved.result == GuardrailResultEnum.BLOCK
        assert retrieved.reason == "amount_requires_human_approval"
    finally:
        conn.close()


# ==============================================================================
# LEVEL 3: SYSTEM TESTING
# ==============================================================================
def test_level_3_system_fastapi_http_workflow():
    """
    [SYSTEM TESTING]
    Objective: Exercise the application end-to-end through its external HTTP API boundary.
    
    Verifies that FastAPI router handling, database querying,
    and HTTP JSON response serialization cooperate seamlessly via the public API.
    """
    client = TestClient(app)
    
    # Act: Request telemetry metrics via public HTTP interface
    response = client.get("/api/metrics?view=demo")
    
    # Assert: End-to-end system response contracts
    assert response.status_code == 200
    data = response.json()
    assert "total_revenue_at_risk" in data
    assert "total_revenue_recovered" in data
    assert "recovery_rate_pct" in data
    assert "transactions_count" in data
    assert "recovered_count" in data
    assert isinstance(data["recovery_rate_pct"], (int, float))


# ==============================================================================
# LEVEL 4: ACCEPTANCE TESTING
# ==============================================================================
def test_level_4_acceptance_zero_unverified_recovery_invariant():
    """
    [ACCEPTANCE TESTING]
    Objective: Validate non-negotiable business acceptance criteria & regulatory invariants.
    
    Business Acceptance Criterion:
    'No recovery event shall ever be marked RECOVERED or recognized as recovered revenue
    without cryptographic or authoritative gateway verification (reconciliation).
    Execution of a recovery action does NOT equal financial recovery.'
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    
    try:
        # Create an active recovery case
        risk = RiskEvent(
            risk_id="risk_accept_lvl4_001",
            event_id="evt_accept_lvl4_001",
            risk_type=RiskType.PAYMENT_FAILED,
            amount=7500.0,
            priority=Priority.MEDIUM,
            status=EventStatus.IN_PROGRESS,
            created_at=datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc),
        )
        insert_risk_event(conn, risk)
        
        # Simulate execution attempt succeeding on gateway mock
        execution = Execution(
            risk_id="risk_accept_lvl4_001",
            action_index=0,
            action_type=ActionType.SMART_RETRY,
            execution_id="exec_accept_lvl4_001",
            status=ExecutionStatusEnum.SUCCESS,
            executed_at=datetime(2026, 10, 8, 10, 5, 0, tzinfo=timezone.utc),
        )
        insert_execution(conn, execution)
        
        # Verify from database: status MUST remain IN_PROGRESS, NOT RECOVERED
        persisted_risk = get_risk_event(conn, "risk_accept_lvl4_001")
        assert persisted_risk is not None
        assert persisted_risk.status != EventStatus.RECOVERED
        assert persisted_risk.status == EventStatus.IN_PROGRESS
    finally:
        conn.close()
