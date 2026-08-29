# BUILD PLAN — phases in strict order. Do not skip ahead.

Mark a phase [x] only when its "Done when" criteria are met AND reflected in STATE.md.

## Phase 1 — Ingestion + Risk Detector + Root Cause Engine (rules only, no LLM yet)
- [x] Normalize schema for payment_failed events
- [x] `risk_events` table + Revenue Risk Detector (rule-based classification)
- [x] Root Cause Engine: error-code → root_cause deterministic map (no LLM yet)
- Done when: one synthetic payment_failed event produces a correct risk_event + root_cause row.

## Phase 2 — Decision Engine (playbook lookup, no LLM yet)
- [x] Implement PLAYBOOK dict exactly as in ARCHITECTURE.md
- [x] `next_action(root_cause, index)` function + `interventions` table
- Done when: given a root_cause + failed action_index, correct next action is returned,
  and None is returned correctly at end of list.

## Phase 3 — Guardrail Layer
- [x] Implement retry_cap_exceeded and dnd_hours rules (these two first — fastest, most demoable)
- [x] `guardrail_checks` table, logs PASS/BLOCK + reason
- Done when: a synthetic case with attempt_number=5 is correctly BLOCKED with reason.

## Phase 4 — Action Executor
- [x] Mocked/sandbox calls for smart_retry, payment_link, reminder, escalate
- [x] `executions` table logs every call with execution_id
- Done when: each action type can be called and logged, success/fail simulated.

## Phase 5 — Outcome Tracker + the loop (core differentiator — do not rush this)
- [x] `handle_outcome()` per ARCHITECTURE.md pseudocode
- [x] On FAILED: advance index, re-run guardrails, execute next action
- [x] On end-of-playbook or BLOCK: call Escalation Handler
- [x] `outcomes` + `escalations` tables
- Done when: a synthetic bank_timeout case fails action 1, succeeds on action 2, and
  ₹ is marked recovered. A separate case exhausts its playbook and is escalated.

## Phase 6 — Audit Trail
- [x] `audit_log` table, one row per state transition across all layers above
- [x] Hook audit logging across ingestion, risk detector, root cause, decision, guardrail, executor, outcome tracker, escalation
- Done when: a single risk_id's full journey can be queried as an ordered list of rows.

## Phase 7 — Batch Dashboard
- [x] Live ₹ recovered counter
- [x] Recovery rate %, breakdown by root cause, breakdown by action
- [x] Blocked count + reasons, escalated count + reasons
- [x] Per-transaction drill-down view
- Done when: a batch of 50-100 synthetic events runs and dashboard updates live.

## Phase 8 — Add LLM (only after 1-7 are solid)
- [x] LLM fallback for root cause when error code missing/ambiguous (fixed enum output)
- [x] LLM drafts customer-facing message for the first chosen action
- Done when: LLM calls are wrapped in try/catch with rule-based fallback if LLM fails/slow.

## Phase 9 — Synthetic batch + demo rehearsal
- [x] Build 50-100 event batch covering all root causes + at least one guardrail block
- [x] Rehearse the exact demo script (see FINAL_PLAN doc, section 5.3)
- Done when: full run-through completed twice without manual intervention.

## POST-MVP EXPANSION (Phases 1-9 must remain stable — cut without hesitation if behind schedule)

## Phase 10 — Razorpay Sandbox + Webhook Hardening (Workstream A)
- [x] DB migration framework (`src/migrations.py`) — `schema_migrations` table for reproducible versioned schema updates (Migration v1: `webhook_events`, Migration v2: `reconciliation_state`)
- [x] Feature flags & config (`src/integrations/config.py`) — `EXECUTION_MODE` (mock/sandbox), `B2B_ENABLED`, `INFO_GATHERING_ENABLED`, `VOICE_ENABLED`, `FAULT_INJECTION_ENABLED`, `DEMO_FALLBACK_TO_MOCK` (default false)
- [x] Razorpay client adapter (`src/integrations/razorpay_client.py`) — thin wrapper around `razorpay` SDK exposing `create_payment_link()`, `fetch_payment()`, `fetch_order()`, `verify_payment_signature()`
- [x] Sandbox Payment Link executor (`src/integrations/sandbox_executor.py`) — real Razorpay Test API call; strict mode separation (`EXECUTION_MODE=sandbox` returns structured `FAILED` or `PENDING_RECONCILIATION` on API error; no silent fallback unless `DEMO_FALLBACK_TO_MOCK=true` is explicitly set)
- [x] Webhook endpoint & lifecycle (`POST /api/webhooks/razorpay`, `src/webhook.py`) — raw body HMAC-SHA256 verification → `x-razorpay-event-id` deduplication; `webhook_events` table tracks lifecycle (`RECEIVED` → `PROCESSING` → `PROCESSED` | `FAILED`)
- [x] Status reconciliation (`src/reconciliation.py`) — `reconcile_payment_status()` API polling when webhook hasn't arrived
- [x] Two-level testing suite — Level A (automated mocked SDK tests in CI) + Level B (manual test-credentials smoke test)
- Done when: all 92+ MVP tests pass AND Level A integration tests pass AND Level B real-credentials sandbox smoke test succeeds before demo AND invalid signatures reject AND duplicate webhooks return 200 without duplicate processing.

## Phase 11 — Network Jitter, Fault Injection & Monotonic State Invariants (Workstream B)
- [x] Fault injector module (`src/fault_injector.py`) — test-only layer supporting `network_timeout`, `transient_5xx`, `duplicate_webhook`, `out_of_order_webhook`, `duplicate_success`, `late_success`, `connection_reset` (gated by `FAULT_INJECTION_ENABLED=true`)
- [x] `PENDING_RECONCILIATION` state-machine invariant — network timeout / uncertain outcome sets state to `PENDING_RECONCILIATION`; blocks all further recovery actions until resolved; never treat timeout as automatic failure
- [x] Reconciliation timeout policy — max 3 reconciliation attempts OR 24 hours elapsed (whichever occurs first) without status resolution forces human escalation (`ESCALATED`)
- [x] Monotonic payment-state transition invariant:
  - External webhook ordering does not dictate internal state ordering.
  - State transitions are strictly monotonic (`DETECTED` → `IN_PROGRESS` → `PENDING_RECONCILIATION` → `RECOVERED` / `ESCALATED` / `FAILED`).
  - Late/older webhooks never move a transaction backward (e.g. `payment.failed` received after `payment.captured` is ignored).
  - `RECOVERED` is terminal and cannot be reverted by any subsequent webhook.
  - Duplicate `payment_success` webhooks create receipt records in `webhook_events` but yield zero duplicate financial transitions.
- [x] External event to internal state mapping:
  - `payment.authorized` / `payment.captured` / `payment_link.paid` → `RECOVERED`
  - `payment.failed` (when unresolved) → `FAILED` (advance playbook)
  - Network timeout / unknown response → `PENDING_RECONCILIATION`
  - Max retries / guardrail block / reconciliation timeout → `ESCALATED`
- [x] Extended idempotency verification — test duplicate webhook, triple success webhook, duplicate outcome, duplicate recovery transition, duplicate execution result, duplicate batch request
- Done when: no duplicate revenue recovery AND no infinite retries AND monotonic state invariant verified AND 3-attempt/24h timeout escalates safely AND audit trail remains ordered.

## Phase 12 — B2B Receivables Recovery (Workstream C)
- [x] Receivables data model & schema (`src/receivables.py`, Migration v3) — `Receivable` model (`receivable_id`, `customer_id`, `invoice_id`, `amount_due`, `due_date`, `days_overdue`, `status`, `customer_tier`, `last_contacted_at`, `promise_to_pay_date`); `receivables` table
- [x] Domain-specific B2B playbooks (`src/decision_engine.py`) — introduce `receivable_overdue: [reminder, payment_link, escalate_to_crm]` and `promise_to_pay_missed: [reminder, payment_link, escalate_to_collections]`; keep existing `recent_overdue` payment-recovery playbook `["reminder", "payment_link"]` untouched
- [x] RiskType vs RootCause separation — `RiskType.RECEIVABLE_OVERDUE` triggers receivables pipeline; playbook lookup keyed strictly on `RootCause`
- [x] Promise-to-pay tracking — record `promise_to_pay_date`, check on due date; payment closes invoice, missed date triggers `promise_to_pay_missed` workflow
- [x] B2B messaging & action handlers — LLM drafts invoice communications; new action handlers `execute_escalate_to_crm()` and `execute_escalate_to_collections()`
- [x] Receivables metrics & dashboard — outstanding amount, overdue amount, recovered receivables, avg days to recovery, promise-to-pay success rate (gated by `B2B_ENABLED=true`)
- Done when: one complete invoice recovery scenario AND one promise-to-pay missed escalation AND guardrails apply to B2B actions AND existing `recent_overdue` payment flow remains unchanged AND all prior tests pass.

## Phase 13 — Information Gathering for Unknown Root Cause (Workstream D)
- [x] `WAITING_FOR_CUSTOMER_INFO` / `INFO_REQUESTED` event states (Migration v4: `info_requests` table)
- [x] Bounded single-question clarification flow (`src/info_gathering.py`) — `can_request_info()` enforces max 1 clarification request; `generate_clarification_question()` drafts question; `parse_customer_response()` extracts structured root cause strictly into fixed enum
- [x] Recovery eligibility & window check — `check_recovery_eligibility()` enforces 7-day recovery window (configurable); verifies payment still unrecovered and amount valid before resuming playbook
- [x] Safety constraints — no payment action during info gathering, DND/opt-out apply to question, silence/timeout → escalation, invalid response → escalation, no conversational loops
- [x] API endpoint `POST /api/info-requests/{risk_id}/respond` (gated by `INFO_GATHERING_ENABLED=true`)
- Done when: unknown → clarification → supported root cause → 7-day eligibility check pass → recovery AND unknown → clarification → expired/unsupported/timeout → escalation AND no money action before classification AND all interactions audited.

## Phase 14 — Hinglish Voice Recovery (Workstream E)
- [x] Contact eligibility pre-check (`src/voice.py`) — `check_voice_eligibility()` verifies opt-out status, DND hours, valid phone number, recovery validity, and human-only rules before initiating outbound call
- [x] Voice pipeline & adapters (`src/voice.py`, `src/integrations/twilio_client.py`) — `TwilioClient` TwiML; `MockSTTAdapter` & `MockTTSAdapter` for deterministic automated tests; pluggable adapters for real providers (Polly Aditi / Google Cloud TTS / Deepgram)
- [x] Hinglish intent classification — `VoiceIntent` enum (`SEND_PAYMENT_LINK`, `CONFIRM_PAYMENT`, `ASK_STATUS`, `SPEAK_TO_HUMAN`, `DECLINE`); classifies transcripts strictly into fixed enum
- [x] Control-plane integration — voice intent feeds into SAME recovery engine, guardrails, and action executor; voice agent CANNOT approve refunds, override guardrails, alter amounts, or execute unapproved actions
- [x] Human handoff — `SPEAK_TO_HUMAN` or unrecognized intent triggers immediate transfer to human agent
- [x] API endpoints `POST /api/voice/call`, `POST /api/voice/interact`, `POST /api/voice/webhook/incoming` (gated by `VOICE_ENABLED=true`)
- Done when: voice eligibility pre-check blocks ineligible contacts AND one successful voice-to-recovery scenario AND one voice-to-human-escalation AND Hinglish test phrases classified correctly AND all prior tests pass.

---

## Current Project Phase

`FINAL QA / DEMO PREPARATION`

**Status Summary**:
- Core MVP (Phases 1–9) = **COMPLETE**
- Post-MVP Expansion (Phases 10–14) = **COMPLETE** (implementation & automated test suite)
- Real external-provider smoke tests = **PENDING** (pending live Razorpay & Twilio/STT/TTS API keys)
- No Phase 15 feature development is currently approved.

**Purpose of Current Phase**:
- Manual QA testing across Dashboard & APIs
- External live credential smoke validation
- Demo script rehearsal & presentation readiness
- Technical documentation & repository handoff
