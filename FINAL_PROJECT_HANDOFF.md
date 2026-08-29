# FINAL PROJECT HANDOFF

**Project Name**: Autonomous AI Revenue Recovery System  
**Track**: Razorpay Buildathon, Track 03  
**Status**: **Phases 1–14 100% Complete & Verified (`151/151 PASSED`)**  
**Current Phase**: `FINAL QA / DEMO PREPARATION`

---

## A. Project Identity
An autonomous, policy-governed revenue recovery platform designed to recover failed payments, checkout abandonments, and overdue B2B receivables. The system diagnoses failure root causes, evaluates deterministic compliance guardrails, executes recovery actions via mock or Razorpay sandbox endpoints, and drives closed-loop retries until recovery or human escalation. Live metrics and multi-layer audit trails are surfaced on a real-time FastAPI + React dashboard.

---

## B. Current State & Verification
- **Automated Tests**: **`151/151 PASSED`** (`pytest -v` across `tests/test_phase1.py` through `tests/test_phase14.py`).
- **Demo Rehearsal Baseline**: **65 synthetic events** processed with **100% reproducible metrics**:
  - Total Revenue At Risk: **`₹6,50,037.00`**
  - Total Revenue Recovered: **`₹3,91,725.00`** (60.26% recovery rate)
  - Guardrail Compliance Hard-Stops: **`8`**
  - Escalations to Ops: **`17`**
- **Engineering Status**: Phases 1 through 14 are complete. Feature development is frozen. Phase 15 is **not** approved.

---

## C. Architecture Layer Summary
1. **Ingestion & Normalization** (`src/ingestion.py`): Ingests webhook/API payloads, normalizes currency amounts into float INR, and creates `risk_events` records.
2. **Revenue Risk Detector** (`src/risk_detector.py`): Assigns priority (`HIGH`, `MEDIUM`, `LOW`) based on amount thresholds and customer VIP status.
3. **Root Cause Engine** (`src/root_cause.py`): Tier 1 deterministic rules (error codes $\rightarrow$ root causes). Tier 2 LLM fallback for ambiguous errors outputting fixed enum values.
4. **Decision Engine** (`src/decision_engine.py`): Looks up next action index from deterministic `PLAYBOOK` table; drafts personalized customer communications via LLM.
5. **Guardrail Layer** (`src/guardrails.py`): Evaluates 6 prioritized compliance rules (`retry_cap_exceeded`, `mandate_notice_required`, `cooldown_active`, `dnd_hours`, `customer_opted_out`, `amount_requires_human_approval`); produces `PASS` or `BLOCK`.
6. **Action Executor** (`src/executor.py`): Executes actions (`smart_retry`, `payment_link`, `reminder`, `discount_nudge`, `escalate`, `escalate_to_crm`, `escalate_to_collections`) with unique execution IDs and mode separation (`mock`/`sandbox`).
7. **Outcome Tracker** (`src/outcome_tracker.py`): Drives closed-loop retries via `handle_outcome()`. Marks `RECOVERED` on success, advances playbook index on failure, or escalates on `BLOCK` / end of playbook.
8. **Audit Trail & Dashboard** (`src/audit.py`, `src/server.py`, UI): Appends structured JSON to `audit_log` for every state transition; powers live web dashboard and REST APIs.

---

## D. Core Control Rules & Principles
- **Playbook Authority**: Retry sequences follow fixed, deterministic playbook lists (`PLAYBOOK` dict). The LLM is **never** permitted to re-decide action order.
- **Deterministic Guardrails**: Guardrails run BEFORE every action execution. A guardrail `BLOCK` immediately halts recovery and escalates to human ops without executing the action.
- **Bounded LLM Scope**: LLM is strictly constrained to root-cause fallback (outputting fixed enums) and drafting text messages.
- **Monotonicity & Reconciliation**: Financial state transitions are monotonic. `RECOVERED` is terminal. Webhook timeouts set state to `PENDING_RECONCILIATION` and block further recovery actions until resolved.
- **Idempotency**: Webhook events are deduplicated by `x-razorpay-event-id`. Duplicate deliveries return HTTP 200 without creating duplicate financial transitions.
- **Immutable Audit Trail**: Append-only log captures every input, output, decision, and timestamp across all layers.

---

## E. Implemented Recovery Domains
1. **Payment Recovery Pipeline**: Closed-loop retries, smart retry, payment links, and customer reminders.
2. **Razorpay Sandbox & Webhooks**: HMAC-SHA256 signature verification, lifecycle state management, and status reconciliation.
3. **B2B Receivables Recovery**: Invoices, overdue tracking, promise-to-pay missed escalation, CRM/collections escalation.
4. **Information Gathering**: Single-question clarification for `UNKNOWN` root cause with 7-day recovery window.
5. **Hinglish Voice Recovery**: Contact eligibility pre-check, Hinglish intent classification, TwiML generation, and pluggable mock/real STT/TTS adapters.

---

## F. Verification & Test Commands

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Run full 151-test suite
pytest -v

# 3. Run double demo rehearsal regression test
python demo_rehearsal.py

# 4. Start FastAPI server for manual UI / API testing
uvicorn src.server:app --port 8000 --host 127.0.0.1
```

- **Dashboard UI**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive API Docs (Swagger)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
