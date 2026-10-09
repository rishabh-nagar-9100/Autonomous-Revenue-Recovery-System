# FT3 Testing Baseline

## Environment
- **Python Version**: `Python 3.9.6` (`darwin / macOS arm64`)
- **Pytest Version**: `pytest 8.4.2` (`pluggy 1.6.0`, `anyio 4.12.1`)
- **Pytest-Cov Version**: `pytest-cov 7.1.0` (`coverage 7.10.7`)
- **Execution Mode**: `mock` (enforced via `tests/conftest.py`)

---

## Existing Test Suite
- **Tests Collected**: `175`
- **Tests Executed**: `175`
- **Passed**: `175`
- **Failed**: `0`
- **Skipped**: `0`
- **Errors**: `0`
- **Warnings**: `1` (`NotOpenSSLWarning: urllib3 v2 LibreSSL 2.8.3 warning`)
- **Duration**: `6.07s` (with branch coverage instrumentation) / `6.51s` (standard run)

### Test File Breakdown
| Test File | Verified Executed Tests | Primary Scope |
|---|:---:|---|
| `tests/test_dashboard_controls.py` | 22 | FastAPI controls, DB view isolation, resets, drilldowns |
| `tests/test_phase1.py` | 15 | Ingestion, normalization, risk detector, root cause rules |
| `tests/test_phase2.py` | 13 | Decision engine playbooks, action lookups, DB persistence |
| `tests/test_phase3.py` | 19 | 6 Safety guardrails, priority order, DB persistence |
| `tests/test_phase4.py` | 16 | Action executor handlers, failure simulation, execution IDs |
| `tests/test_phase5.py` | 8 | Outcome tracker closed loop, multi-step retries, escalations |
| `tests/test_phase6.py` | 5 | Append-only audit logging & 9-layer lineage reconstruction |
| `tests/test_phase7.py` | 6 | Synthetic batch runner, metrics aggregation, KPI endpoints |
| `tests/test_phase8.py` | 9 | Tiered LLM fallback, timeout handling, message drafting |
| `tests/test_phase9.py` | 3 | Deterministic 65-event benchmark double rehearsal |
| `tests/test_phase10.py` | 15 | Razorpay client adapter, HMAC signatures, webhook idempotency |
| `tests/test_phase11.py` | 8 | Fault injection, chaos resilience, 5xx/timeouts |
| `tests/test_phase12.py` | 8 | B2B receivables recovery, >90 day overdue rules, CRM handoff |
| `tests/test_phase13.py` | 12 | Bounded clarification, 7-day window, single request cap |
| `tests/test_phase14.py` | 16 | Hinglish voice recovery, phone number checks, TwiML adapters |
| **Total** | **175** | **100% Passed** |

---

## Statement Coverage

- **Overall Statement Coverage**: **`85%`**
- **Total Statements**: `2,182`
- **Missed Statements**: `336`

### Per-File Statement Coverage
| File | Statements | Missed | Statement Cover % | Missing Line Ranges |
|---|:---:|:---:|:---:|---|
| `src/__init__.py` | 0 | 0 | 100% | None |
| `src/decision_engine.py` | 21 | 0 | 100% | None |
| `src/integrations/sandbox_executor.py` | 22 | 0 | 100% | None |
| `src/metrics.py` | 66 | 0 | 100% | None |
| `src/migrations.py` | 27 | 0 | 100% | None |
| `src/models.py` | 185 | 0 | 100% | None |
| `src/pipeline.py` | 18 | 0 | 100% | None |
| `src/root_cause.py` | 39 | 0 | 100% | None |
| `src/guardrails.py` | 56 | 1 | 98% | 48 |
| `src/audit.py` | 33 | 1 | 97% | 19 |
| `src/outcome_tracker.py` | 95 | 4 | 96% | 90, 94, 268, 272 |
| `src/executor.py` | 61 | 3 | 95% | 128-129, 188 |
| `src/integrations/config.py` | 56 | 3 | 95% | 23-24, 34 |
| `src/db.py` | 176 | 10 | 94% | 340, 379, 415, 651, 734-739 |
| `src/batch_runner.py` | 111 | 8 | 93% | 35-42, 152-154, 199, 271 |
| `src/info_gathering.py` | 108 | 10 | 91% | 36, 65, 142, 156, 172, 175, 178, 181, 208, 220 |
| `src/ingestion.py` | 49 | 5 | 90% | 18, 22, 26, 31-32 |
| `src/fault_injector.py` | 41 | 4 | 90% | 40, 61, 65-66 |
| `src/voice.py` | 146 | 19 | 87% | 46, 61, 97, 106, 114, 126, 171, 261-275, 278-279, 282-283 |
| `src/receivables.py` | 58 | 10 | 83% | 124-136, 169-170 |
| `src/llm.py` | 95 | 17 | 82% | 31-36, 53, 97-98, 103, 105, 107, 112, 149, 202-203, 208 |
| `src/webhook.py` | 169 | 33 | 80% | 37, 48, 82, 87, 92, 98, 128-138, 206-207, 260-268, 274, 276, 338-341, 373-383 |
| `src/risk_detector.py` | 18 | 5 | 72% | 23-28 |
| `src/reconciliation.py` | 134 | 45 | 66% | 59, 61, 84, 219, 221, 306-371 |
| `src/server.py` | 320 | 123 | 62% | 84-86, 95-104, 109-113, 151-152, 166-167, 236, 245, 270-433, 480 |
| `src/integrations/razorpay_client.py` | 54 | 22 | 59% | 69, 81-82, 86-89, 93-96, 100-103, 112-121, 134 |
| `src/integrations/twilio_client.py` | 24 | 13 | 46% | 17-33, 53-69 |

---

## Branch Coverage

- **Overall Branch Coverage (Statements + Branches)**: **`82%`**
- **Total Branch Points**: `570`
- **Partial Branches (Uncovered Conditions)**: `100`

### Per-File Branch Breakdown
| File | Branches | Partial Branches | Combined Cover % | Uncovered Branch Targets |
|---|:---:|:---:|:---:|---|
| `src/decision_engine.py` | 6 | 0 | 100% | Fully covered |
| `src/migrations.py` | 4 | 0 | 100% | Fully covered |
| `src/metrics.py` | 4 | 0 | 100% | Fully covered |
| `src/integrations/sandbox_executor.py` | 4 | 0 | 100% | Fully covered |
| `src/root_cause.py` | 20 | 1 | 98% | `165->176` (Tier 1 vs Tier 2 fallback condition) |
| `src/guardrails.py` | 18 | 1 | 97% | `47->49` (`default_guardrail_time` hour check) |
| `src/audit.py` | 12 | 1 | 96% | Line 19 (non-dict serialization fallback) |
| `src/executor.py` | 8 | 1 | 94% | `127->131` (metadata channel fallback) |
| `src/outcome_tracker.py` | 26 | 5 | 93% | `89->91`, `93->95`, `267->269`, `271->273`, `292->303` |
| `src/db.py` | 30 | 6 | 91% | `657->659`, `661->664`, error handling queries |
| `src/integrations/config.py` | 14 | 3 | 91% | `13->27`, `21->16` (.env parsing line conditions) |
| `src/batch_runner.py` | 42 | 5 | 90% | `201->204` (batch delay callbacks) |
| `src/info_gathering.py` | 42 | 10 | 87% | Parsing fallbacks and eligibility checks |
| `src/ingestion.py` | 14 | 3 | 87% | Event mapping default paths |
| `src/voice.py` | 48 | 9 | 85% | `245->251`, phone parser edge cases |
| `src/fault_injector.py` | 16 | 5 | 84% | Injected fault probability gates |
| `src/receivables.py` | 16 | 3 | 80% | `69->72` (overdue days fallback calc) |
| `src/llm.py` | 46 | 12 | 77% | `93->100`, `198->205` (LLM schema parse branches) |
| `src/webhook.py` | 86 | 16 | 76% | `17->21`, `42->44`, `73->79`, `79->85` (Nested note extractors) |
| `src/risk_detector.py` | 10 | 1 | 64% | `23->25`, `25->27` (cart_abandonment & recent_overdue branches) |
| `src/reconciliation.py` | 54 | 10 | 62% | `104->109`, `176->178`, `233->249`, `306-371` |
| `src/server.py` | 42 | 5 | 59% | `228->235`, `471->475`, endpoints routes |
| `src/integrations/razorpay_client.py` | 4 | 2 | 59% | Real API request dispatch branches |
| `src/integrations/twilio_client.py` | 4 | 1 | 43% | Real Twilio HTTP dispatch branches |

---

## Current Testing Gaps
Based strictly on unexecuted lines and uncovered branch targets from pytest-cov:

1. **`src/risk_detector.py` Branch Incompleteness**:
   - Lines 23-28: The `event_type == "cart_abandonment"` and `event_type == "recent_overdue"` branches in `detect_revenue_risk()` are currently bypassed in dedicated detector tests.
2. **`src/reconciliation.py` Live Poller Daemon**:
   - Lines 306-371: The `poll_live_razorpay_payments()` function which polls the Razorpay API for live payment statuses is not exercised under mock test execution.
   - Line 84: Transition handling for late failure events arriving against already-`RECOVERED` risk events is partially unexercised.
3. **`src/webhook.py` Fallback Parsing**:
   - Lines 128-138: Event hash generation when neither header event ID nor entity ID is supplied.
   - Lines 260-268: Description token matching fallback when reference ID is not present in notes.
4. **Boundary Condition Testing Gaps**:
   - Guardrails lack exact floating-point boundary checks (`₹49,999.99` vs `₹50,000.00` vs `₹50,000.01`).
   - Risk detector lacks exact boundary checks (`₹2,499.99` vs `₹2,500.00`, `₹9,999.99` vs `₹10,000.00`).
   - Cooldown timer lacks exact second checks (`14,399s` vs `14,400s`).
   - DND hours lack minute-level checks (`08:59` vs `09:00`, `19:59` vs `20:00`).
5. **Real Client Integration Stubs**:
   - `twilio_client.py` and `razorpay_client.py` have low coverage (43% and 59%) because tests strictly execute with `EXECUTION_MODE="mock"` (via `conftest.py`).

---

## Important Note: Collection vs. Execution
- **Tests Collected**: **`175`** (via AST / pytest collection)
- **Tests Executed**: **`175`** (confirmed via dynamic pytest test runner)
- **Tests Passed**: **`175`** (100% green, 0 failures, 0 errors, 0 skips)
- There is a 1-to-1 parity between collected test items and executed passing tests.
