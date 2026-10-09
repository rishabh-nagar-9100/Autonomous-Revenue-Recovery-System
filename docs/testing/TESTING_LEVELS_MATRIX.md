# Testing Levels Traceability Matrix

**Autonomous Revenue Recovery System — Software Testing FT3**  
**Document**: `docs/testing/TESTING_LEVELS_MATRIX.md`  
**Purpose**: Comprehensive classification and evidence mapping of the repository's automated test suite across the four standard levels of software testing: Unit, Integration, System, and Acceptance.

---

## 1. Executive Summary

Software testing in the Autonomous Revenue Recovery System is organized across four hierarchical levels. Each level addresses a distinct scope of validation, from fine-grained algorithmic logic to end-to-end business acceptance criteria:

```
+-------------------------------------------------------------------+
|                        ACCEPTANCE TESTING                         |
|   Regulatory compliance (RBI/TRAI), financial monotonicity,       |
|          65-event deterministic benchmark, zero-hallucination     |
+-------------------------------------------------------------------+
                                  ^
+-------------------------------------------------------------------+
|                          SYSTEM TESTING                           |
|       FastAPI REST endpoints (/api/metrics, /api/run-batch),      |
|           batch orchestration, dashboard simulation APIs          |
+-------------------------------------------------------------------+
                                  ^
+-------------------------------------------------------------------+
|                        INTEGRATION TESTING                        |
|    Cross-layer pipelines (Ingestion -> Risk -> DB, Webhook ->     |
|   Reconciliation, Executor -> SQLite -> Immutable Audit Trail)    |
+-------------------------------------------------------------------+
                                  ^
+-------------------------------------------------------------------+
|                           UNIT TESTING                            |
|       Isolated pure functions (guardrails, risk thresholds,       |
|         root cause mapping, regex provenance, intent parsing)     |
+-------------------------------------------------------------------+
```

---

## 2. Testing Levels Classification Matrix

| Testing Level | Objective & Scope | Representative Test Node IDs | Components Covered | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Unit Testing** | Verify individual functions and algorithmic decisions in isolation without cascading dependencies. | `tests/test_phase1.py::TestRevenueRiskDetector::test_high_priority_for_large_amounts`<br>`tests/test_phase2.py::TestDecisionEnginePlaybook::test_all_playbook_sequences[bank_timeout]`<br>`tests/test_phase3.py::TestRetryCapGuardrail::test_attempt_number_5_blocked_with_retry_cap_exceeded`<br>`tests/ft3/test_boundary_value_analysis.py::TestRiskDetectorAmountBVA::test_amount_at_2500_boundary`<br>`tests/ft3/test_equivalence_partitioning.py::TestVoiceEngineECP::test_voice_intent_extraction_hinglish`<br>`tests/ft3/test_white_box.py::TestWebhookWhiteBox::test_wb_webhook_extract_ref_order_receipt` | `src/risk_detector.py`<br>`src/root_cause.py`<br>`src/guardrails.py`<br>`src/decision_engine.py`<br>`src/webhook.py`<br>`src/voice.py` | Fast in-memory execution (<1ms/test); isolated function outputs validated against deterministic inputs. |
| **Integration Testing** | Verify interface contracts, data handoffs, and transactional persistence across two or more collaborating subsystems. | `tests/test_phase1.py::TestPhase1DatabaseAndDoneCriteria::test_phase1_end_to_end_done_when_criterion`<br>`tests/test_phase3.py::TestGuardrailDatabasePersistenceAndDoneCriteria::test_guardrail_check_persisted_to_sqlite`<br>`tests/test_phase4.py::TestActionExecutor::test_execution_persisted_to_sqlite`<br>`tests/test_phase6.py::TestAuditTrail::test_log_audit_appends_and_serializes_structured_json`<br>`tests/test_phase11.py::TestPhase11WebhookIngestion::test_webhook_ingestion_signature_and_deduplication`<br>`tests/test_phase12.py::TestPhase12ReconciliationState::test_payment_authorized_pending_capture_flow`<br>`tests/test_phase13.py::TestPhase13B2BReceivablesRecovery::test_b2b_receivable_ingestion_and_pipeline` | `src/ingestion.py`<br>`src/guardrails.py`<br>`src/executor.py`<br>`src/db.py`<br>`src/audit.py`<br>`src/reconciliation.py`<br>`src/receivables.py` | Multi-table SQLite database state changes; verified foreign key relationships and append-only audit hashes. |
| **System Testing** | Exercise the entire application stack end-to-end through public application interfaces (HTTP REST APIs and Batch Runner). | `tests/test_phase7.py::TestFastAPIServerEndpoints::test_metrics_and_batch_endpoints`<br>`tests/test_phase7.py::TestBatchRunnerAndMetrics::test_run_synthetic_batch_updates_database_and_computes_metrics`<br>`tests/test_dashboard_controls.py::TestDashboardEndpoints::test_get_metrics_endpoint`<br>`tests/test_dashboard_controls.py::TestDashboardEndpoints::test_manual_trigger_recovery_endpoint`<br>`tests/test_phase8.py::TestPhase8EndToEndScenarios::test_end_to_end_pipeline_with_llm_diagnosed_root_cause` | `src/server.py`<br>`src/batch_runner.py`<br>`src/pipeline.py`<br>Complete 8-Layer Pipeline | FastAPI `TestClient` HTTP requests (`GET /api/metrics`, `POST /api/run-batch`); validates HTTP 200, JSON schema, and multi-step pipeline lifecycle. |
| **Acceptance Testing** | Validate explicit business acceptance criteria, financial invariants, benchmark targets, and regulatory standards. | `tests/test_phase9.py::TestPhase9DemoRehearsal::test_rehearsal_batch_deterministic_reproducibility`<br>`tests/test_phase9.py::TestPhase9DemoRehearsal::test_double_rehearsal_produces_identical_metrics`<br>`tests/test_phase5.py::TestPhase5DoneWhenCriteria::test_mock_action_success_does_not_equal_recovery`<br>`tests/test_phase5.py::TestPhase5DoneWhenCriteria::test_zero_verified_recovery_equals_zero_amount_recovered`<br>`tests/test_phase12.py::TestPhase12ReconciliationState::test_monotonic_recovered_terminal_invariant`<br>`tests/test_phase3.py::TestMandateNoticeGuardrail::test_mandate_without_notice_blocks_retry`<br>`tests/test_phase3.py::TestDndHoursGuardrail::test_customer_facing_action_during_night_dnd_is_blocked`<br>`tests/test_phase5.py::TestOutcomeTrackerScenarios::test_chronic_non_payer_escalates_immediately` | Entire Autonomous Revenue Recovery System | Deterministic 65-transaction rehearsal batch consistency; financial non-reversion proofs; strict regulatory compliance checks. |

---

## 3. Detailed Level 1: Unit Testing Inventory

| Test ID | Function / Module | Input Data | Expected Output | Rationale for Unit Classification |
| :--- | :--- | :--- | :--- | :--- |
| `test_high_priority_for_large_amounts` | `detect_revenue_risk` (`src/risk_detector.py`) | `amount = 12000.0`, `is_vip = False` | `RiskEvent.priority == Priority.HIGH` | Pure function test; no database or external service involved. |
| `test_bank_timeout_mapping` | `diagnose_root_cause_rules` (`src/root_cause.py`) | `error_code = "GATEWAY_TIMEOUT"` | `RootCause.root_cause == RootCauseEnum.BANK_TIMEOUT` | Evaluates string lookup against static set in memory. |
| `test_all_playbook_sequences[bank_timeout]` | `next_action` (`src/decision_engine.py`) | `root_cause = "bank_timeout"`, `index = 0` | `ActionType.SMART_RETRY` | Deterministic dictionary lookup test in isolation. |
| `test_attempt_number_5_blocked_with_retry_cap_exceeded` | `evaluate_guardrails` (`src/guardrails.py`) | `attempt_number = 5`, `action = SMART_RETRY` | `result == BLOCK`, `reason == "retry_cap_exceeded"` | Validates isolated threshold check on `GuardrailContext`. |
| `test_wb_webhook_extract_ref_order_receipt` | `extract_reference_id` (`src/webhook.py`) | Nested JSON payload with order receipt | `"risk_ord_receipt_99"` | Pure parser logic handling dictionary key navigation. |
| `test_voice_intent_extraction_hinglish` | `extract_hinglish_intent` (`src/voice.py`) | `"bhej do payment link sms pe"` | `VoiceIntent.SEND_PAYMENT_LINK` | Substring match NLP parser tested in memory. |
| `test_info_gathering_empty_or_none_response` | `parse_customer_response` (`src/info_gathering.py`) | `""`, `None`, `"   "` | `None` | Defensive string sanitizer unit test. |

---

## 4. Detailed Level 2: Integration Testing Inventory

| Test ID | Collaborating Components | Data Flow & Interfaces Tested | Expected Result | Integration Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `test_phase1_end_to_end_done_when_criterion` | `src/ingestion.py` $\leftrightarrow$ `src/risk_detector.py` $\leftrightarrow$ `src/root_cause.py` $\leftrightarrow$ `src/db.py` | Raw dictionary $\to$ `NormalizedEvent` $\to$ `RiskEvent` $\to$ `RootCause` $\to$ SQLite insert/read | Risk event and root cause records correctly persisted and retrievable from SQLite | Validates serialization and data contract compliance across three sequential modules and the database layer. |
| `test_guardrail_check_persisted_to_sqlite` | `src/guardrails.py` $\leftrightarrow$ `src/db.py` $\leftrightarrow$ `src/audit.py` | `evaluate_and_record_guardrails(...)` | Row inserted into `guardrail_checks` table + entry written to `audit_log` | Validates transactional integration between guardrail decision making and SQLite persistence. |
| `test_webhook_ingestion_signature_and_deduplication` | `src/webhook.py` $\leftrightarrow$ `src/integrations/razorpay_client.py` $\leftrightarrow$ `src/db.py` | Raw HTTP body + HMAC-SHA256 signature $\to$ Verification adapter $\to$ `webhook_events` deduplication table | First call records event; second identical call returns `duplicate_skipped` | Tests cryptographic adapter integration with database deduplication table. |
| `test_payment_authorized_pending_capture_flow` | `src/reconciliation.py` $\leftrightarrow$ `src/db.py` $\leftrightarrow$ `src/audit.py` | Inbound `payment.authorized` status $\to$ SQLite status update check | Status remains `IN_PROGRESS`; audit layer records `payment_authorized_pending_capture` | Tests financial state machine integration with database and audit trail. |
| `test_b2b_receivable_ingestion_and_pipeline` | `src/receivables.py` $\leftrightarrow$ `src/outcome_tracker.py` $\leftrightarrow$ `src/db.py` | B2B invoice data $\to$ Receivable table $\to$ Risk event $\to$ Workflow initiation | Invoiced amount tracked, root cause evaluated, and workflow dispatched | Tests multi-table relational persistence and pipeline orchestration. |

---

## 5. Detailed Level 3: System Testing Inventory

| Test ID | Entry Point | End-to-End System Flow | Expected Result | System Testing Rationale |
| :--- | :--- | :--- | :--- | :--- |
| `test_metrics_and_batch_endpoints` | FastAPI `TestClient` (`GET /api/metrics`, `POST /api/run-batch`) | HTTP Client $\to$ FastAPI ASGI App $\to$ Batch Runner $\to$ Database Aggregation $\to$ JSON Response | HTTP 200 OK, JSON structure matches telemetry specification | Exercises the entire running software system through external HTTP endpoints. |
| `test_run_synthetic_batch_updates_database_and_computes_metrics` | `run_synthetic_batch(...)` (`src/batch_runner.py`) | Synthetic generator $\to$ 8-layer autonomous pipeline $\to$ SQLite database $\to$ Analytics metrics engine | Batch executes across 65 events; total recovered, recovery rate, and escalation metrics calculated | Exercises the complete business application workflow without external mocking. |
| `test_manual_trigger_recovery_endpoint` | FastAPI `TestClient` (`POST /api/trigger-recovery`) | HTTP Client $\to$ FastAPI route handler $\to$ SQLite lookup $\to$ Outcome Tracker workflow $\to$ DB update | HTTP 200, workflow resumes, audit trail appended | Tests full system trigger mechanism from API layer down to database. |
| `test_end_to_end_pipeline_with_llm_diagnosed_root_cause` | Complete Pipeline Entry | Raw payment failure $\to$ Rule engine unknown $\to$ Mock LLM client $\to$ Playbook dispatch $\to$ Guardrails $\to$ Outcome | Risk event recovered via LLM diagnosed root cause | Exercises the full cognitive recovery pipeline from ingestion to resolution. |

---

## 6. Detailed Level 4: Acceptance Testing Inventory

| Test ID | Business Requirement | Explicit Acceptance Criterion | Actual Result |
| :--- | :--- | :--- | :--- |
| `test_rehearsal_batch_deterministic_reproducibility` | Deterministic Recovery Baseline | A 65-event rehearsal batch must produce identical financial recovery metrics across independent runs. | **PASSED**: Exact metric parity achieved across runs (0 variance). |
| `test_double_rehearsal_produces_identical_metrics` | System Determinism & Audit Immutability | Re-running the identical synthetic batch against a fresh database must yield identical recovery counts and amounts. | **PASSED**: Total recovered amounts and transaction states match to 4 decimal places. |
| `test_mock_action_success_does_not_equal_recovery` | Financial Verification Safety | A successful communication action (e.g. SMS reminder sent) must NEVER be marked as financial recovery. | **PASSED**: Amount recovered remains ₹0.00 until payment capture is verified. |
| `test_monotonic_recovered_terminal_invariant` | Non-Reversion Invariant | A transaction that has reached `RECOVERED` must NEVER be reverted by subsequent failed webhooks. | **PASSED**: Late failure events are ignored; terminal state is strictly preserved. |
| `test_mandate_without_notice_blocks_retry` | RBI e-Mandate Regulatory Compliance | Automated payment retries against recurring mandates must be blocked unless a pre-debit notice was served. | **PASSED**: System blocks execution with `mandate_notice_required`. |
| `test_customer_facing_action_during_night_dnd_is_blocked` | TRAI DND Compliance | Customer-facing communications (SMS, WhatsApp, Voice) are strictly prohibited between 20:00 and 09:00. | **PASSED**: Blocked with reason `dnd_hours`; backend retries allowed. |
| `test_chronic_non_payer_escalates_immediately` | Fraud & Credit Risk Acceptance | Customers classified as chronic non-payers must be immediately escalated to human operations with 0 auto-discounts. | **PASSED**: Escalated immediately with open ticket; no automated nudge sent. |
