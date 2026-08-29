# PROJECT CONTEXT — READ THIS FIRST, EVERY SESSION

## What this is
Autonomous AI Revenue Recovery System for Razorpay Buildathon, Track 03. Detects revenue at risk (failed payments, checkout abandonment, overdue receivables), diagnoses root cause, picks a compliant recovery action from a fixed playbook, executes it, and if it fails, tries the next allowed action until success or a guardrail/exhausted-playbook forces escalation to a human. Every step is logged. Batch dashboard shows live ₹ recovered.

## Core Architecture Principle
AI is bounded by deterministic financial control mechanisms. Rules and deterministic state machines maintain authoritative control over financial execution, retry limits, compliance guardrails, and state transitions. The LLM provides intelligent root-cause diagnosis for ambiguous errors and drafts personalized customer communications, but **never** makes unconstrained financial execution decisions.

## Control-Plane Rules
- **LLM does not control unrestricted financial action.**
- **Playbook policy remains authoritative.** Retry sequences follow fixed ordered lists.
- **Guardrails remain deterministic and hard-stop.** Guardrails evaluate BEFORE every action execution.
- **Action Executor is the execution boundary.** Generates unique execution IDs and handles sandbox/mock separation.
- **Outcome Tracker controls recovery progression.** Drives closed-loop retries, advances playbook indices, and enforces monotonicity.
- **Audit trail records all state transitions.** Append-only log captures every layer from ingestion to final status.

## Current Supported Scope
The system supports 4 integrated recovery domains:
1. **Payment Failure Recovery**: Closed-loop retries, smart retry, payment links, and reminders.
2. **B2B Receivables Recovery**: Invoice overdue, promise-to-pay tracking, CRM escalation, collections escalation.
3. **Information Gathering**: Single-question customer clarification for `UNKNOWN` root cause with 7-day recovery eligibility window.
4. **Hinglish Voice Recovery**: Pre-call contact eligibility, Hinglish intent classification (`SEND_PAYMENT_LINK`, `CONFIRM_PAYMENT`, `ASK_STATUS`, `SPEAK_TO_HUMAN`, `DECLINE`), TwiML markup generation, and mock/real STT/TTS adapters.

## Architecture Constraints (DO NOT VIOLATE)
- Do NOT introduce LLM-controlled arbitrary financial actions.
- Do NOT bypass guardrails or create backdoors around compliance checks.
- Do NOT change playbook sequencing without an explicit project-lead decision.
- Do NOT silently replace sandbox execution with mock (mode separation must be explicit).
- Do NOT treat uncertain payment outcomes as automatic failures (use `PENDING_RECONCILIATION`).
- Do NOT bypass webhook idempotency (`x-razorpay-event-id`).
- Do NOT create parallel or duplicate financial execution engines.

## Current Synthetic Demo Baseline
- Synthetic Batch Size: **65 Events**
- Revenue at Risk: **₹6,50,037.00**
- Revenue Recovered: **₹3,91,725.00** (60.26% recovery rate)
- Guardrail Compliance Blocks: **8**
- Escalations to Ops: **17**

## External Validation Status
- **Automated Test Suite**: 151/151 tests passed (`pytest -v`).
- **Real Razorpay Test Mode Smoke Test**: **Pending external API credentials**.
- **Real Twilio / STT / TTS Smoke Test**: **Pending external provider API credentials**.

## Reference Documentation
- Architecture Details: see [ARCHITECTURE.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/ARCHITECTURE.md)
- Phase Build Order & Status: see [BUILD_PLAN.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/BUILD_PLAN.md) and [STATE.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/STATE.md)
- Architectural Decisions: see [DECISIONS.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/DECISIONS.md)
