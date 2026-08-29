# ARCHITECTURE (condensed reference — do not redesign without flagging in DECISIONS.md)

## Core Pipeline Flow
```text
EVENT / CUSTOMER INPUT
  │
  ▼
1. INGESTION & NORMALIZATION → normalizes raw events into single schema, writes risk_events
  │
  ▼
2. REVENUE RISK DETECTOR → risk_type, amount_at_risk, priority
  │
  ▼
3. ROOT CAUSE ENGINE → rules first, LLM fallback (fixed enum output only)
  │
  ▼
4. DECISION ENGINE → picks action_index from fixed ordered playbook, drafts message via LLM
  │
  ▼
5. GUARDRAIL LAYER → deterministic pre-action checks; can hard-stop (PASS / BLOCK)
  │
  ▼
6. ACTION EXECUTOR → mock/sandbox execution; logs execution_id
  │
  ▼
7. OUTCOME TRACKER → drives retry loop. SUCCESS: mark RECOVERED. FAILED: advance action_index,
   re-evaluate guardrails, execute next action. End of playbook or BLOCK → Escalation Handler
  │
  ▼
8. AUDIT TRAIL & DASHBOARD → append-only audit_log; live metrics & UI drill-down
```

## Non-Negotiable Rule
**LLM $\neq$ Financial Control Plane.**  
The LLM provides intelligent root-cause diagnosis for unmapped signals and drafts personalized customer messages. The LLM **never** decides retry sequencing, bypasses guardrails, or overrides financial execution boundaries. Playbook rules and guardrails remain 100% deterministic and authoritative.

## The Playbook Table
```python
PLAYBOOK = {
    "bank_timeout":        ["smart_retry", "payment_link"],
    "nsf":                 ["delayed_retry", "payment_link"],
    "expired_card":        ["payment_link", "reminder"],
    "cart_abandonment":    ["discount_nudge", "reminder"],
    "recent_overdue":      ["reminder", "payment_link"],
    "chronic_non_payer":   [],   # empty = escalate immediately to human ops
    
    # B2B Receivables Domain Extensions
    "receivable_overdue":      ["reminder", "payment_link", "escalate_to_crm"],
    "promise_to_pay_missed":  ["reminder", "payment_link", "escalate_to_collections"],
}
```

## Guardrail Rules (Evaluated in Strict Priority Order)
1. `retry_cap_exceeded`: max 4 attempts total per transaction
2. `mandate_notice_required`: RBI e-mandate pre-debit notice window
3. `cooldown_active`: no more than 1 retry per 4h on same transaction
4. `dnd_hours`: no customer-facing action outside 9am-8pm
5. `customer_opted_out`: skip customer-facing actions if customer opted out
6. `amount_requires_human_approval`: amount above threshold (>₹50,000) forces human escalation

## Post-MVP Architecture Extensions
1. **Razorpay Sandbox Integration**: `EXECUTION_MODE=sandbox` integrates with Razorpay Test Mode API (`create_payment_link`). Webhooks verify raw HMAC-SHA256 signature and deduplicate via `x-razorpay-event-id`.
2. **Reconciliation & Monotonicity Engine**: `reconcile_payment_status()` polls API when webhooks are delayed. Network timeouts transition state to `PENDING_RECONCILIATION` and block further recovery actions. State transitions are strictly monotonic (`DETECTED` $\rightarrow$ `IN_PROGRESS` $\rightarrow$ `PENDING_RECONCILIATION` $\rightarrow$ `RECOVERED` / `ESCALATED` / `FAILED`). `RECOVERED` is terminal.
3. **Fault Injection Engine**: Test-only module simulating `network_timeout`, `transient_5xx`, `duplicate_webhook`, `out_of_order_webhook`, and `late_success` (gated by `FAULT_INJECTION_ENABLED=true`).
4. **B2B Receivables Recovery**: Ingests overdue invoices (`receivables` table), tracks `promise_to_pay_date`, and routes through B2B-specific playbooks without altering the existing payment recovery playbook.
5. **Information Gathering**: Single-question customer clarification for `UNKNOWN` root cause (`info_requests` table). Enforces max 1 clarification request and a 7-day recovery eligibility window (`INFO_RECOVERY_WINDOW_DAYS = 7`).
6. **Hinglish Voice Recovery Interface**: Outbound voice call eligibility pre-check (`check_voice_eligibility`), Hinglish intent classification (`VoiceIntent` enum), TwiML XML markup generation (`Polly.Aditi` `hi-IN`), pluggable `MockSTTAdapter` & `MockTTSAdapter`, and Voice interaction persistence (`voice_interactions` table).

## Database Schema Overview (12 Application Tables + Migration Metadata)
- **Application Tables**: `risk_events`, `root_causes`, `interventions`, `guardrail_checks`, `executions`, `outcomes`, `escalations`, `audit_log`, `webhook_events`, `receivables`, `info_requests`, `voice_interactions`.
- **Migration Metadata Table**: `schema_migrations` (tracks applied schema migrations v1 to v5).
