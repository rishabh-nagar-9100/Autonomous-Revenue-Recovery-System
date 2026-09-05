import pytest
import sqlite3
from datetime import datetime
from src.models import (
    RiskEvent,
    RootCause,
    RiskType,
    Priority,
    EventStatus,
    RootCauseEnum,
    ActionType,
    ExecutionStatusEnum,
    OutcomeResultEnum,
    EscalationStatusEnum,
)
from src.db import (
    init_db,
    insert_risk_event,
    insert_root_cause,
    get_risk_event,
    get_outcomes_for_risk,
    get_escalation,
    get_executions_for_risk,
    get_guardrail_checks_for_risk,
)
from src.guardrails import GuardrailContext
from src.outcome_tracker import handle_outcome, start_recovery_workflow


# Standard business hours context (2:00 PM) to ensure tests are deterministic
DAYTIME_CONTEXT = GuardrailContext(
    current_time=datetime(2026, 8, 27, 14, 0, 0)
)


@pytest.fixture
def in_memory_db():
    """Provides an initialized in-memory SQLite database connection for testing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def setup_test_risk_and_root_cause(
    conn: sqlite3.Connection,
    risk_id: str,
    root_cause_enum: RootCauseEnum,
    amount: float = 10000.0,
):
    risk = RiskEvent(
        risk_id=risk_id,
        event_id=f"pay_{risk_id}",
        risk_type=RiskType.PAYMENT_FAILED,
        amount=amount,
        priority=Priority.HIGH,
        status=EventStatus.DETECTED,
    )
    insert_risk_event(conn, risk)

    rc = RootCause(
        risk_id=risk_id,
        root_cause=root_cause_enum,
        confidence=1.0,
        source="rule",
    )
    insert_root_cause(conn, rc)
    return risk, rc


class TestOutcomeTrackerScenarios:
    def test_immediate_success_stops_workflow_and_marks_recovered(self, in_memory_db):
        setup_test_risk_and_root_cause(in_memory_db, "risk_succ_01", RootCauseEnum.BANK_TIMEOUT, 5000.0)

        # Simulation: Action 0 (smart_retry) succeeds (interventions dispatched)
        result = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_succ_01",
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={0: ExecutionStatusEnum.SUCCESS},
        )

        # Action execution success leaves status IN_PROGRESS with amount_recovered=0.0
        assert result.final_status == EventStatus.IN_PROGRESS
        assert result.amount_recovered == 0.0
        assert result.actions_executed_count == 1

        # Verify DB state before reconciliation
        risk = get_risk_event(in_memory_db, "risk_succ_01")
        assert risk.status == EventStatus.IN_PROGRESS

        # Perform verified payment reconciliation
        from src.reconciliation import reconcile_payment_status
        recon = reconcile_payment_status(in_memory_db, "risk_succ_01", forced_status="RECOVERED")
        assert recon["status"] == "reconciled"

        risk_after = get_risk_event(in_memory_db, "risk_succ_01")
        assert risk_after.status == EventStatus.RECOVERED

        outcomes = get_outcomes_for_risk(in_memory_db, "risk_succ_01")
        assert len(outcomes) >= 1
        assert outcomes[-1].result == OutcomeResultEnum.SUCCESS
        assert outcomes[-1].amount_recovered == 5000.0

        # No escalation created
        assert get_escalation(in_memory_db, "risk_succ_01") is None

        # Only 1 execution occurred
        execs = get_executions_for_risk(in_memory_db, "risk_succ_01")
        assert len(execs) == 1
        assert execs[0].action_type == ActionType.SMART_RETRY

    def test_scenario_1_bank_timeout_fail_action0_succeed_action1(self, in_memory_db):
        """
        Critical Scenario 1:
        bank_timeout -> smart_retry FAILED -> payment_link SUCCESS -> payment reconciliation -> ₹ recovered
        """
        setup_test_risk_and_root_cause(in_memory_db, "risk_scen_1", RootCauseEnum.BANK_TIMEOUT, 15000.0)

        # Simulation: Action 0 fails, Action 1 succeeds (dispatched)
        result = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_scen_1",
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={
                0: ExecutionStatusEnum.FAILED,
                1: ExecutionStatusEnum.SUCCESS,
            },
        )

        assert result.final_status == EventStatus.IN_PROGRESS
        assert result.amount_recovered == 0.0
        assert result.actions_executed_count == 2

        from src.reconciliation import reconcile_payment_status
        reconcile_payment_status(in_memory_db, "risk_scen_1", forced_status="RECOVERED")

        # Verify risk event status after reconciliation
        risk = get_risk_event(in_memory_db, "risk_scen_1")
        assert risk.status == EventStatus.RECOVERED

    def test_scenario_2_bank_timeout_all_failed_playbook_exhausted(self, in_memory_db):
        """
        Critical Scenario 2:
        bank_timeout -> smart_retry FAILED -> payment_link FAILED -> escalation (playbook exhausted)
        """
        setup_test_risk_and_root_cause(in_memory_db, "risk_scen_2", RootCauseEnum.BANK_TIMEOUT, 8000.0)

        # Simulation: Action 0 fails, Action 1 fails
        result = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_scen_2",
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={
                0: ExecutionStatusEnum.FAILED,
                1: ExecutionStatusEnum.FAILED,
            },
        )

        assert result.final_status == EventStatus.ESCALATED
        assert result.amount_recovered == 0.0
        assert result.reason == "playbook_exhausted"
        assert result.actions_executed_count == 2

        # Verify outcomes
        outcomes = get_outcomes_for_risk(in_memory_db, "risk_scen_2")
        assert len(outcomes) == 2
        assert outcomes[0].result == OutcomeResultEnum.FAILED
        assert outcomes[1].result == OutcomeResultEnum.FAILED

        # Verify escalation record
        escalation = get_escalation(in_memory_db, "risk_scen_2")
        assert escalation is not None
        assert escalation.reason == "playbook_exhausted"
        assert escalation.status == EscalationStatusEnum.OPEN

        # Verify risk event status
        risk = get_risk_event(in_memory_db, "risk_scen_2")
        assert risk.status == EventStatus.ESCALATED

    def test_scenario_3_guardrail_block_stops_workflow_and_escalates(self, in_memory_db):
        """
        Critical Scenario 3:
        FAILED -> next action (payment_link) -> guardrail BLOCK (DND night time) -> escalation
        Next action is NOT executed in executions table.
        """
        setup_test_risk_and_root_cause(in_memory_db, "risk_scen_3", RootCauseEnum.BANK_TIMEOUT, 10000.0)

        # Context: Current time is 23:00 (11 PM night, DND violation for customer-facing payment_link)
        ctx = GuardrailContext(
            current_time=datetime(2026, 8, 27, 23, 0, 0)
        )

        result = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_scen_3",
            context=ctx,
            simulated_action_outcomes={
                0: ExecutionStatusEnum.FAILED,  # smart_retry allowed during DND, but fails
                1: ExecutionStatusEnum.SUCCESS,  # payment_link will be blocked by DND guardrail
            },
        )

        assert result.final_status == EventStatus.ESCALATED
        assert result.reason == "guardrail_blocked:dnd_hours"

        # Verify guardrail checks
        checks = get_guardrail_checks_for_risk(in_memory_db, "risk_scen_3")
        assert len(checks) == 2
        assert checks[0].action_index == 0
        assert checks[0].result.value == "PASS"  # smart_retry passed
        assert checks[1].action_index == 1
        assert checks[1].result.value == "BLOCK"  # payment_link blocked by DND
        assert checks[1].reason == "dnd_hours"

        # Verify executions: only action 0 was executed. Action 1 was BLOCKED and NEVER executed!
        execs = get_executions_for_risk(in_memory_db, "risk_scen_3")
        assert len(execs) == 1
        assert execs[0].action_type == ActionType.SMART_RETRY

        # Verify escalation record
        escalation = get_escalation(in_memory_db, "risk_scen_3")
        assert escalation is not None
        assert escalation.reason == "guardrail_blocked:dnd_hours"

    def test_chronic_non_payer_escalates_immediately(self, in_memory_db):
        setup_test_risk_and_root_cause(in_memory_db, "risk_chronic", RootCauseEnum.CHRONIC_NON_PAYER, 20000.0)

        result = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_chronic",
            context=DAYTIME_CONTEXT,
        )

        assert result.final_status == EventStatus.ESCALATED
        assert result.reason == "playbook_exhausted"
        assert result.actions_executed_count == 0

        # No executions performed
        execs = get_executions_for_risk(in_memory_db, "risk_chronic")
        assert len(execs) == 0

        # Escalation recorded
        escalation = get_escalation(in_memory_db, "risk_chronic")
        assert escalation is not None
        assert escalation.reason == "playbook_exhausted"


class TestPhase5DoneWhenCriteria:
    def test_phase5_done_when_criteria(self, in_memory_db):
        """
        Phase 5 "Done when" criteria:
        1. A synthetic bank_timeout case fails action 1, succeeds on action 2, and after payment reconciliation is marked recovered.
        2. A separate case exhausts its playbook and is escalated.
        """
        # Case 1: Recovers on action 2
        setup_test_risk_and_root_cause(in_memory_db, "risk_done_1", RootCauseEnum.BANK_TIMEOUT, 25000.0)
        res_1 = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_done_1",
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={
                0: ExecutionStatusEnum.FAILED,
                1: ExecutionStatusEnum.SUCCESS,
            },
        )
        assert res_1.final_status == EventStatus.IN_PROGRESS
        assert res_1.amount_recovered == 0.0

        from src.reconciliation import reconcile_payment_status
        reconcile_payment_status(in_memory_db, "risk_done_1", forced_status="RECOVERED")
        risk_1 = get_risk_event(in_memory_db, "risk_done_1")
        assert risk_1.status == EventStatus.RECOVERED

        # Case 2: Exhausts playbook and escalates
        setup_test_risk_and_root_cause(in_memory_db, "risk_done_2", RootCauseEnum.EXPIRED_CARD, 4500.0)
        # expired_card playbook: payment_link (0) -> reminder (1) -> escalate
        res_2 = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_done_2",
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={
                0: ExecutionStatusEnum.FAILED,
                1: ExecutionStatusEnum.FAILED,
            },
        )
        assert res_2.final_status == EventStatus.ESCALATED
        assert res_2.amount_recovered == 0.0
        assert res_2.reason == "playbook_exhausted"
        escalation_2 = get_escalation(in_memory_db, "risk_done_2")
        assert escalation_2 is not None
        assert escalation_2.reason == "playbook_exhausted"
        risk_2 = get_risk_event(in_memory_db, "risk_done_2")
        assert risk_2.status == EventStatus.ESCALATED

    def test_mock_action_success_does_not_equal_recovery(self, in_memory_db):
        """Rule: Action execution success alone does NOT mark financial recovery."""
        setup_test_risk_and_root_cause(in_memory_db, "risk_semantic_01", RootCauseEnum.BANK_TIMEOUT, 1000.0)
        res = start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_semantic_01",
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={0: ExecutionStatusEnum.SUCCESS},
        )
        assert res.final_status == EventStatus.IN_PROGRESS
        assert res.amount_recovered == 0.0
        risk = get_risk_event(in_memory_db, "risk_semantic_01")
        assert risk.status == EventStatus.IN_PROGRESS

    def test_zero_verified_recovery_equals_zero_amount_recovered(self, in_memory_db):
        """Rule: Unverified transaction must have amount_recovered == 0.0."""
        setup_test_risk_and_root_cause(in_memory_db, "risk_semantic_02", RootCauseEnum.NSF, 2500.0)
        start_recovery_workflow(
            conn=in_memory_db,
            risk_id="risk_semantic_02",
            context=DAYTIME_CONTEXT,
            simulated_action_outcomes={0: ExecutionStatusEnum.SUCCESS},
        )
        outcomes = get_outcomes_for_risk(in_memory_db, "risk_semantic_02")
        assert len(outcomes) == 1
        assert outcomes[0].amount_recovered == 0.0
