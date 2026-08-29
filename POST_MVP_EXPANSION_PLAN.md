# Post-MVP Expansion Plan — AI Revenue Recovery Agent

## 0. Purpose

This document defines the post-MVP engineering roadmap for expanding the completed Razorpay Track 03 AI Revenue Recovery system.

The MVP (Phases 1–9) remains the stable baseline. The expansion must preserve the existing control-plane principles:

- Rules/ML provide deterministic facts and risk signals.
- LLM reasoning is bounded.
- The recovery PLAYBOOK remains policy-controlled.
- Guardrails remain deterministic and can hard-stop.
- Action Executor is the only execution boundary.
- Outcome Tracker drives workflow state transitions.
- Every important state transition is auditable.
- New capabilities must not weaken payment safety or idempotency.

The five approved expansion areas are:

1. Razorpay Test/Sandbox API integration
2. Network jitter and asynchronous failure testing
3. B2B receivables recovery workflow
4. Information Gathering for unknown root causes
5. Hinglish voice recovery

These should be implemented in the order below. Do not attempt all five simultaneously.

---

# 1. Target Post-MVP Architecture

```text
                         ┌─────────────────────────────┐
                         │        EVENT SOURCES        │
                         │                             │
                         │ Razorpay Webhooks           │
                         │ Checkout / Payment Events   │
                         │ Subscription Events         │
                         │ Invoice / Receivables       │
                         │ Voice / Customer Responses  │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ 1. INGESTION & NORMALIZATION│
                         │                             │
                         │ validation                  │
                         │ signature verification     │
                         │ deduplication / idempotency│
                         │ event ordering tolerance    │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ 2. REVENUE / RECEIVABLES    │
                         │    RISK DETECTOR            │
                         │                             │
                         │ payment risk                │
                         │ overdue invoice risk        │
                         │ recovery priority           │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ 3. ROOT CAUSE ENGINE         │
                         │                             │
                         │ deterministic rules          │
                         │          ↓                  │
                         │ LLM fallback if ambiguous   │
                         │          ↓                  │
                         │ Information Gathering       │
                         │          ↓                  │
                         │ supported cause / escalate  │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ 4. POLICY / PLAYBOOK ENGINE │
                         │                             │
                         │ approved recovery strategies│
                         │ domain-specific sequences   │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ 5. DETERMINISTIC GUARDRAILS │
                         │                             │
                         │ amount limits               │
                         │ retry/cooldown             │
                         │ consent / DND              │
                         │ mandate rules               │
                         │ human approval              │
                         │ idempotency                 │
                         └──────────────┬──────────────┘
                                        │
                            ┌───────────┴───────────┐
                            │                       │
                          PASS                    BLOCK
                            │                       │
                            ▼                       ▼
                 ┌────────────────────┐   ┌────────────────────┐
                 │ 6. ACTION EXECUTOR │   │ ESCALATION / HUMAN │
                 │                    │   │ REVIEW             │
                 │ Mock adapter       │   └──────────┬─────────┘
                 │ Sandbox adapter    │              │
                 │ Voice adapter      │              │
                 │ Messaging adapter  │              │
                 └─────────┬──────────┘              │
                           │                         │
                           └───────────┬─────────────┘
                                       ▼
                         ┌─────────────────────────────┐
                         │ 7. OUTCOME / STATE MACHINE │
                         │                             │
                         │ success → recovered        │
                         │ failure → next action      │
                         │ uncertain → wait/reconcile │
                         │ terminal → escalation      │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ 8. AUDIT + OBSERVABILITY    │
                         │                             │
                         │ audit trail                 │
                         │ metrics                     │
                         │ latency / errors            │
                         │ API traces                  │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────┐
                         │ 9. OPERATIONS DASHBOARD     │
                         │                             │
                         │ recovery + receivables      │
                         │ voice interactions          │
                         │ failures / retries          │
                         │ pending human reviews       │
                         └─────────────────────────────┘
```

---

# 2. Non-Negotiable Control Principles

## 2.1 Do not turn the LLM into the financial control plane

The post-MVP system may become more dynamic, but the LLM must never directly:

- move money,
- issue a refund,
- bypass a guardrail,
- alter compliance rules,
- create an arbitrary action,
- retry indefinitely,
- approve a high-value transaction.

Any LLM recommendation must pass through policy and deterministic guardrails.

## 2.2 Preserve execution adapters

Do not delete mock execution just because sandbox APIs are added.

Use:

```text
ExecutionMode
├── mock
└── razorpay_sandbox
```

This allows:

- deterministic automated tests,
- fast batch simulation,
- realistic sandbox demonstrations.

## 2.3 Idempotency is mandatory

Razorpay webhook delivery can contain duplicate events, and webhook events may arrive out of order. The webhook integration must therefore deduplicate events using the event identifier and must not assume delivery order.

Razorpay documents the unique `x-razorpay-event-id` header for duplicate-event handling and explicitly warns that webhook order may not always match event order. citeturn325460search0turn325460search6

## 2.4 Verify signed webhooks

Every real Razorpay webhook integration must verify the `X-Razorpay-Signature` against the raw request body using the webhook secret before processing the event. citeturn325460search0turn325460search11

## 2.5 Sandbox first

Razorpay provides Test/Sandbox mode specifically for testing API integrations without real money. Use Test API keys and sandbox behavior before any consideration of live credentials. citeturn325460search3

---

# 3. Workstream A — Razorpay Test/Sandbox API Integration

## Goal

Replace selected mock actions with real Razorpay Test Mode integrations while retaining mocks for deterministic testing.

## Scope

Integrate these actions first:

1. Payment Link creation
2. Payment status retrieval
3. Payment verification
4. Webhook ingestion
5. Optional: subscription-related test flows

Payment Links are especially suitable because Razorpay provides APIs for creating, fetching, updating, cancelling, and notifying customers about Payment Links. citeturn325460search7turn325460search13

## Architecture

```text
Action Executor
      │
      ├── MockExecutor
      │
      └── RazorpaySandboxExecutor
                │
                ▼
          Razorpay Test API
                │
                ▼
             Webhook
                │
                ▼
       Signature Verification
                │
                ▼
          Event Ingestion
```

## Implementation

### Step A1 — Configuration

Add:

```text
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
EXECUTION_MODE=mock|sandbox
```

Never commit credentials.

### Step A2 — Razorpay client adapter

Create a dedicated module:

```text
src/integrations/razorpay_client.py
```

Expose narrow methods such as:

```text
create_payment_link()
fetch_payment()
fetch_order()
verify_payment()
```

Do not expose raw client behavior to business logic.

### Step A3 — Sandbox Payment Link

Use the Razorpay Payment Links API for selected demo transactions.

Important: Razorpay currently documents a Test Mode limit of 30 Payment Links per business, so the full 65-event synthetic batch should remain mock-driven rather than creating 65 live sandbox links. citeturn325460search13

Recommended demo pattern:

```text
65-event batch
→ mock mode

2–3 showcase transactions
→ Razorpay sandbox
```

### Step A4 — Webhook endpoint

Create:

```text
POST /api/webhooks/razorpay
```

Processing sequence:

```text
raw request body
      ↓
signature verification
      ↓
x-razorpay-event-id extraction
      ↓
duplicate check
      ↓
enqueue/process
      ↓
audit
```

Razorpay recommends returning HTTP 200 quickly and processing webhook events asynchronously rather than doing heavy work inline. citeturn325460search11

### Step A5 — Status reconciliation

Because webhooks are asynchronous, add:

```text
webhook received
      ↓
expected status not observed?
      ↓
API fetch
      ↓
reconcile
```

Razorpay's webhook documentation recommends API fetch as a supplement when a critical user-facing flow needs immediate confirmation and a webhook has not arrived yet. citeturn325460search6

## Acceptance criteria

- sandbox Payment Link can be created
- payment status can be queried
- valid webhook signature accepted
- invalid signature rejected
- duplicate webhook ignored
- delayed webhook does not corrupt state
- mock mode remains fully functional
- no live credentials required

---

# 4. Workstream B — Network Jitter & Asynchronous Failure Testing

## Goal

Prove that the recovery state machine survives realistic distributed-system behavior.

## Fault Injection Layer

Create a test-only component:

```text
Action Executor
      ↓
Fault Injector
      ↓
Mock / Sandbox Adapter
```

Supported faults:

```text
network_timeout
artificial_delay
transient_5xx
duplicate_webhook
out_of_order_webhook
duplicate_success
late_success
connection_reset
```

## Deterministic fault scenarios

Example:

```text
smart_retry sent
      ↓
network timeout
      ↓
executor uncertain
      ↓
DO NOT automatically assume success/failure
      ↓
fetch payment status
      ↓
reconcile actual state
```

This is better than blindly treating a timeout as a failed payment.

## State-machine requirement

Introduce an optional execution state:

```text
SUCCESS
FAILED
UNKNOWN / PENDING_RECONCILIATION
```

Do not move to the next recovery action while the previous action's financial outcome is genuinely uncertain.

## Idempotency tests

Simulate:

```text
payment_success webhook
payment_success webhook
payment_success webhook
```

Expected:

```text
one recovery amount
one terminal recovered state
three webhook receipts
zero duplicate money accounting
```

## Out-of-order tests

Simulate:

```text
payment.captured
arrives before
payment.authorized
```

The state machine must not corrupt the transaction.

## Load / concurrency testing

Start with:

```text
10 concurrent events
50 concurrent events
100 concurrent events
```

Measure:

- processing latency
- duplicate rate
- state consistency
- database locking errors
- failed API calls

## Acceptance criteria

- no duplicate revenue recovery
- no infinite retries
- uncertain execution reconciles safely
- duplicate/out-of-order webhooks don't corrupt state
- audit trail remains complete and ordered
- metrics remain correct after injected failures

---

# 5. Workstream C — B2B Receivables Recovery

## Goal

Extend the engine from payment failures to overdue B2B invoices without creating an independent recovery system.

## New domain entity

Add:

```text
receivables
```

Suggested fields:

```text
receivable_id
customer_id
invoice_id
amount_due
due_date
days_overdue
status
customer_tier
last_contacted_at
promise_to_pay_date
```

## Risk detection

Classify:

```text
recent_overdue
chronic_non_payer
promise_to_pay_missed
```

The existing root-cause vocabulary can be extended only through an explicit architecture decision if a new category is genuinely needed.

## B2B workflow

```text
Invoice due
   ↓
Payment missing
   ↓
Days overdue calculated
   ↓
Customer payment history
   ↓
Recovery priority
   ↓
Approved B2B playbook
   ↓
Guardrail
   ↓
Reminder / Payment Link / Escalation
   ↓
Outcome
```

## Suggested B2B playbook

Keep it deterministic.

```text
recent_overdue:
    reminder
    payment_link
    escalate_to_crm

promise_to_pay_missed:
    reminder
    payment_link
    escalate_to_collections

chronic_non_payer:
    immediate human escalation
```

Do not allow the LLM to invent collection actions.

## Message strategy

LLM may draft the communication:

```text
"Your invoice INV-1024 for ₹2,50,000 is overdue.
You can complete the payment using the attached payment link."
```

But:

```text
LLM → draft
Guardrails → allowed?
Executor → send
```

## Promise-to-pay

Support:

```text
Customer:
"I will pay on Friday."

System:
promise_to_pay_date = Friday
```

Then:

```text
Friday
 ↓
payment received?
 ↙        ↘
YES       NO
 ↓         ↓
close     reminder/escalate
```

Limit automated chasing to finite attempts.

## Dashboard additions

Add:

- total outstanding
- overdue amount
- recovered receivables
- average days to recovery
- promise-to-pay success rate
- escalated receivables

## Acceptance criteria

- invoice becomes overdue correctly
- recovery priority is assigned
- approved message generated
- guardrails apply
- payment link can be issued
- payment receipt closes the receivable
- missed promise-to-pay escalates
- all steps are audited

---

# 6. Workstream D — Information Gathering for Unknown Root Cause

## Goal

Reduce unnecessary escalation while preserving safety.

Current safe behavior:

```text
unknown
 ↓
no approved playbook
 ↓
escalate
```

Enhanced behavior:

```text
unknown
 ↓
bounded information request
 ↓
ONE customer response
 ↓
structured extraction
 ↓
supported root cause?
   ↙          ↘
 YES          NO
 ↓             ↓
playbook     escalate
```

## Important boundary

Information gathering is NOT allowed to execute money movement.

It can only gather information.

## New state

Add:

```text
WAITING_FOR_CUSTOMER_INFO
```

Possible lifecycle:

```text
UNKNOWN
   ↓
INFO_REQUESTED
   ↓
CUSTOMER_RESPONDED
   ↓
ROOT_CAUSE_REEVALUATION
   ↓
SUPPORTED / UNKNOWN
```

## Example

Payment failure:

```text
Unknown reason
```

Agent sends:

> "We couldn't complete your payment. Was the issue related to your card, bank account, or another payment method?"

Customer:

> "Mera card expire ho gaya hai."

LLM extracts:

```json
{
  "root_cause": "expired_card",
  "confidence": 0.96
}
```

Then:

```text
expired_card
 ↓
payment_link
 ↓
guardrails
 ↓
execute
```

## Safety constraints

- maximum 1 clarification request
- no payment action during information gathering
- customer consent/opt-out rules still apply
- DND rules still apply
- invalid/ambiguous response → escalate
- customer silence → timeout → escalate

## Acceptance criteria

- unknown can enter info-gathering state
- exactly one bounded clarification is allowed
- answer is converted to a fixed supported root-cause enum
- unsupported answers escalate
- no money action occurs before successful classification
- every interaction is audited

---

# 7. Workstream E — Hinglish Voice Recovery

## Goal

Add voice as an interface to the existing recovery engine, not as a separate decision system.

## Architecture

```text
Customer
   ↓
Twilio Voice
   ↓
Media Stream
   ↓
Speech-to-Text
   ↓
Intent / Response Extraction
   ↓
Existing Recovery Agent
   ↓
Existing Guardrails
   ↓
Existing Action Executor
   ↓
Text-to-Speech
   ↓
Customer
```

Twilio supports bidirectional Media Streams using `<Connect><Stream>`, allowing a WebSocket application to receive audio and send audio back into the call. citeturn325460search12turn325460search8

## Phase E1 — Voice intent only

Start without full autonomous conversation.

Support intents such as:

```text
SEND_PAYMENT_LINK
CONFIRM_PAYMENT
ASK_STATUS
SPEAK_TO_HUMAN
DECLINE
```

Example:

Customer:
> "Haan, payment link bhej do."

STT:

```text
haan payment link bhej do
```

LLM/intent parser:

```json
{
  "intent": "SEND_PAYMENT_LINK"
}
```

Then:

```text
Guardrail
 ↓
create_payment_link()
```

## Phase E2 — Hinglish understanding

Test phrases such as:

```text
"Payment fail ho gaya hai"
"Link bhej do"
"Main kal payment karunga"
"Abhi nahi kar sakta"
"Agent se baat karwao"
```

Normalize them into structured intent.

## Phase E3 — Voice response

Generate concise TTS responses:

> "Theek hai, main aapko payment link bhej deta hoon."

Never let free-form conversation bypass the existing action pipeline.

## Voice safety

The voice agent cannot:

- approve refunds,
- override guardrails,
- alter amount,
- change payment recipient,
- bypass opt-out,
- execute unapproved actions.

## Acceptance criteria

- Twilio connection established
- Hinglish speech transcribed correctly for test phrases
- supported intents classified correctly
- unsupported requests escalate
- actions still pass guardrails
- voice interaction appears in audit trail
- human handoff works

---

# 8. Implementation Order

Do not build these in parallel.

## Phase A — Sandbox + Webhook Hardening

1. Razorpay client adapter
2. Test credentials
3. Payment Link sandbox
4. signed webhook verification
5. event-id deduplication
6. API/webhook reconciliation
7. mock/sandbox switch

**Gate:** all tests + one successful sandbox transaction.

---

## Phase B — Reliability / Fault Injection

1. Fault injector
2. timeout state
3. delayed webhook
4. duplicate webhook
5. out-of-order webhook
6. idempotency
7. reconciliation
8. concurrency tests

**Gate:** no duplicate recovery and no state corruption.

---

## Phase C — B2B Receivables

1. receivables data model
2. overdue detector
3. B2B playbook
4. messaging
5. payment link
6. promise-to-pay
7. escalation
8. dashboard extension

**Gate:** one complete invoice recovery and one escalation scenario.

---

## Phase D — Unknown Information Gathering

1. waiting-for-info state
2. bounded question
3. customer-response parser
4. fixed root-cause extraction
5. timeout
6. escalation

**Gate:** unknown → clarification → supported root cause → recovery AND unknown → clarification → still unknown → escalation.

---

## Phase E — Hinglish Voice

1. Twilio integration
2. media stream
3. speech-to-text
4. intent extraction
5. existing recovery action
6. guardrails
7. text-to-speech
8. human handoff
9. audit integration

**Gate:** successful voice-to-recovery scenario plus voice-to-human escalation.

---

# 9. Testing Strategy

Maintain the existing 92-test suite.

Do not replace it.

Add test groups:

```text
tests/
├── phase1/
├── phase2/
├── phase3/
├── phase4/
├── phase5/
├── phase6/
├── phase7/
├── phase8/
├── phase9/
├── sandbox/
├── reliability/
├── receivables/
├── information_gathering/
└── voice/
```

Run:

```bash
pytest -v
```

after every workstream.

Final target should be:

```text
Existing 92 tests
+
new expansion tests
=
all green
```

The exact final count should not be artificially targeted; correctness matters more than test-count inflation.

---

# 10. New Observability Metrics

Add:

### Sandbox

- API latency
- API success/failure
- webhook delay
- reconciliation count

### Reliability

- duplicate events
- out-of-order events
- uncertain executions
- reconciliation success
- fault-injection failures

### Receivables

- overdue amount
- recovered amount
- average recovery time
- promise-to-pay conversion

### Information Gathering

- unknown-root-cause count
- clarification success rate
- clarification escalation rate

### Voice

- calls
- successful intents
- fallback rate
- human handoffs
- average call duration

---

# 11. Demo Strategy After Expansion

The final presentation should NOT become a 20-minute feature tour.

Use one connected story:

```text
1. Razorpay sandbox payment fails
          ↓
2. Agent detects ₹25,000 at risk
          ↓
3. Root cause is ambiguous
          ↓
4. LLM fallback / information gathering
          ↓
5. Root cause = expired card
          ↓
6. Payment Link selected
          ↓
7. Guardrail passes
          ↓
8. Real Razorpay sandbox Payment Link created
          ↓
9. Customer uses Hinglish voice:
   "Link bhej do"
          ↓
10. Payment confirmed
          ↓
11. Webhook arrives late
          ↓
12. System reconciles state
          ↓
13. ₹25,000 recovered
          ↓
14. Full audit trail
```

Then show:

```text
B2B invoice
 ↓
overdue
 ↓
reminder
 ↓
promise-to-pay
 ↓
payment
 ↓
recovered
```

This makes all the new capabilities feel like one coherent product rather than five disconnected features.

---

# 12. Success Metrics for the Expanded System

The final dashboard should answer:

```text
How much revenue was at risk?
How much was recovered?
How many recovery attempts succeeded?
How many were blocked?
How many required humans?
How many events were duplicated?
How many async events were reconciled?
How much B2B receivables were recovered?
How often did information gathering resolve unknowns?
How many voice interactions resulted in recovery?
```

The most important metric remains:

```text
Revenue Recovered
```

with the caveat that synthetic/demo recovery percentages are not production benchmarks.

---

# 13. What NOT to Do

Do not:

- replace the deterministic architecture with an LLM-controlled agent;
- remove mock execution;
- run all 65 synthetic events against external sandbox APIs;
- let voice bypass the recovery engine;
- let customer responses directly trigger payment actions;
- treat network timeout as automatic payment failure;
- assume webhook ordering;
- allow unlimited clarification;
- add multiple new root-cause enums without an explicit decision;
- start another major feature before the current workstream passes its acceptance gate.

---

# 14. Engineering Governance

For every workstream:

```text
Plan
 ↓
Implement
 ↓
Unit tests
 ↓
Integration tests
 ↓
Runtime inspection
 ↓
Full regression
 ↓
Update STATE.md
 ↓
Review
 ↓
Next workstream
```

Record architectural changes in `DECISIONS.md`.

The existing project-control process should continue to be used. The original architecture and build plan were intentionally designed around phase gates and explicit state tracking.

---

# 15. Final Target Architecture Outcome

After all approved upgrades, the product should be able to handle:

```text
PAYMENT FAILURE
       │
       ├── known cause ───────────────► recovery
       │
       └── unknown
             │
             ▼
       information gathering
          │         │
        known     unknown
          │         │
          ▼         ▼
      recovery   human review


B2B RECEIVABLE
       │
       ▼
   overdue risk
       │
       ▼
   recovery playbook
       │
       ▼
 payment/reminder
       │
       ▼
 recovery/escalation


VOICE
       │
       ▼
   Hinglish intent
       │
       ▼
 existing recovery engine
       │
       ▼
 guardrails
       │
       ▼
 action


EXTERNAL EVENTS
       │
       ▼
 webhook verification
       │
       ▼
 deduplication
       │
       ▼
 asynchronous processing
       │
       ▼
 reconciliation
       │
       ▼
 correct financial state
```

The resulting system remains a **bounded financial agent**, but becomes more realistic, multimodal, resilient, and extensible.

---

# 16. Immediate Next Action

Start with **Workstream A — Razorpay Sandbox + Webhook Hardening**.

Do not start B2B, voice, or information gathering simultaneously.

The first implementation milestone should be:

```text
Razorpay Test Payment
        ↓
Webhook
        ↓
Signature validation
        ↓
Idempotency check
        ↓
Existing ingestion pipeline
        ↓
Existing recovery engine
        ↓
Existing audit trail
```

Once that works reliably, move to fault injection, then B2B, then information gathering, then voice.

## External references

Razorpay's current documentation confirms Test/Sandbox API usage, signed webhook verification, duplicate webhook handling, asynchronous webhook delivery, and Payment Link APIs. citeturn325460search0turn325460search3turn325460search6turn325460search7

Twilio's current Media Streams documentation confirms bidirectional WebSocket audio streams suitable for conversational voice applications. citeturn325460search12turn325460search8
