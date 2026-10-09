# Equivalence Class Partitioning (ECP) Test Matrix

This matrix divides all major input domains of the Autonomous AI Revenue Recovery System into logically equivalent classes. For each class, representative inputs (away from BVA boundaries) are selected, and existing test coverage is documented.

---

## 1. Revenue Risk Detector (`src/risk_detector.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-RD-01** | Amount & VIP | Low value, non-VIP (`amount < 2500.0`, `is_vip=False`) | `amount=1200.0`, `metadata={}` | `Priority.LOW` | Already covered by `test_phase1.py::test_low_priority` |
| **ECP-RD-02** | Amount & VIP | Medium value, non-VIP (`2500.0 <= amount < 10000.0`, `is_vip=False`) | `amount=6500.0`, `metadata={}` | `Priority.MEDIUM` | Already covered by `test_phase1.py::test_medium_priority` |
| **ECP-RD-03** | Amount & VIP | High value, non-VIP (`amount >= 10000.0`, `is_vip=False`) | `amount=18000.0`, `metadata={}` | `Priority.HIGH` | Already covered by `test_phase1.py::test_high_priority_for_large_amounts` |
| **ECP-RD-04** | Amount & VIP | VIP flag override (`is_vip=True`) | `amount=500.0`, `metadata={"is_vip": True}` | `Priority.HIGH` | Already covered by `test_phase1.py::test_high_priority_for_vip_metadata` |
| **ECP-RD-05** | Amount & VIP | VIP customer tier override (`customer_tier="vip"`) | `amount=750.0`, `metadata={"customer_tier": "vip"}` | `Priority.HIGH` | **MISSING** — Added in Phase 4 |
| **ECP-RD-06** | Event Type | Payment failed event (`event_type="payment_failed"`) | `event_type="payment_failed"` | `RiskType.PAYMENT_FAILED` | Already covered by `test_phase1.py::test_high_priority_for_large_amounts` |
| **ECP-RD-07** | Event Type | Cart abandonment event (`event_type="cart_abandonment"`) | `event_type="cart_abandonment"` | `RiskType.CART_ABANDONMENT` | **MISSING** — Added in Phase 4 |
| **ECP-RD-08** | Event Type | Recent overdue event (`event_type="recent_overdue"`) | `event_type="recent_overdue"` | `RiskType.RECENT_OVERDUE` | **MISSING** — Added in Phase 4 |
| **ECP-RD-09** | Event Type | Unrecognized event type (fallback) | `event_type="subscription_halted"` | `RiskType.PAYMENT_FAILED` | **MISSING** — Added in Phase 4 |

---

## 2. Root Cause Engine (`src/root_cause.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-RC-01** | Gateway Errors | Recognized bank timeout code / reason | `code="GATEWAY_TIMEOUT"`, `reason="bank_timeout"` | `RootCauseEnum.BANK_TIMEOUT` (conf: 1.0) | Already covered by `test_phase1.py::test_root_cause_rule_matching` |
| **ECP-RC-02** | Insufficient Funds | Recognized NSF code / reason | `code="INSUFFICIENT_FUNDS"`, `reason="low_balance"` | `RootCauseEnum.NSF` (conf: 1.0) | Already covered by `test_phase1.py::test_root_cause_rule_matching` |
| **ECP-RC-03** | Expired Card | Recognized expired card code / reason | `code="EXPIRED_CARD"`, `reason="card_expired"` | `RootCauseEnum.EXPIRED_CARD` (conf: 1.0) | Already covered by `test_phase1.py::test_root_cause_rule_matching` |
| **ECP-RC-04** | Cart Abandonment | Cart abandonment event type / reason | `event_type="cart_abandonment"`, `reason="checkout_dropoff"` | `RootCauseEnum.CART_ABANDONMENT` (conf: 1.0) | Already covered by `test_phase1.py::test_root_cause_rule_matching` |
| **ECP-RC-05** | Recent Overdue | Invoice overdue event type / reason | `event_type="recent_overdue"`, `reason="invoice_overdue_1_day"` | `RootCauseEnum.RECENT_OVERDUE` (conf: 1.0) | Already covered by `test_phase1.py::test_root_cause_rule_matching` |
| **ECP-RC-06** | Chronic Default | Defaulter flag in metadata (`is_chronic_defaulter=True`) | `metadata={"is_chronic_defaulter": True}` | `RootCauseEnum.CHRONIC_NON_PAYER` (conf: 1.0) | Already covered by `test_phase1.py::test_root_cause_rule_matching` |
| **ECP-RC-07** | Chronic Default | Chronic risk profile metadata (`customer_risk_profile="chronic_non_payer"`) | `metadata={"customer_risk_profile": "chronic_non_payer"}` | `RootCauseEnum.CHRONIC_NON_PAYER` (conf: 1.0) | **MISSING** — Added in Phase 4 |
| **ECP-RC-08** | Unmapped Rules | Unknown code/reason with rule-only diagnosis | `code="UNMAPPED_ERR_999"`, `reason="unknown_failure"` | `RootCauseEnum.UNKNOWN` (conf: 0.0) | **MISSING** — Added in Phase 4 |
| **ECP-RC-09** | Tier 2 LLM | Unmapped error with active LLM fallback | `error_description="Customer bank declined transaction"` | Queries LLM fallback (`source="llm"`) | Already covered by `test_phase8.py::test_case_b_ambiguous_error_calls_llm` |

---

## 3. Safety Guardrails (`src/guardrails.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-GR-01** | Action Category | Non-retry & non-customer action during DND/cooldown | `ActionType.ESCALATE`, `hour=23`, `elapsed=100s` | `GuardrailResultEnum.PASS` | **MISSING** — Added in Phase 4 |
| **ECP-GR-02** | Mandate Check | Mandate notice missing on RETRY action | `is_mandate=True`, `notice=False`, `action=SMART_RETRY` | `GuardrailResultEnum.BLOCK` (`mandate_notice_required`) | Already covered by `test_phase3.py::test_mandate_without_notice_blocks_retry` |
| **ECP-GR-03** | Mandate Check | Mandate notice missing on CUSTOMER-FACING action | `is_mandate=True`, `notice=False`, `action=PAYMENT_LINK` | `GuardrailResultEnum.PASS` (notice only blocks retries) | **MISSING** — Added in Phase 4 |
| **ECP-GR-04** | Cooldown | Cooldown active on non-retry action | `elapsed=600s`, `action=PAYMENT_LINK` | `GuardrailResultEnum.PASS` (cooldown only blocks retries) | **MISSING** — Added in Phase 4 |
| **ECP-GR-05** | Customer Opt-Out | Opted-out customer on customer-facing action | `opted_out=True`, `action=REMINDER` | `GuardrailResultEnum.BLOCK` (`customer_opted_out`) | Already covered by `test_phase3.py::test_customer_opted_out_blocks_customer_facing_action` |
| **ECP-GR-06** | Customer Opt-Out | Opted-out customer on backend retry action | `opted_out=True`, `action=SMART_RETRY` | `GuardrailResultEnum.PASS` (opt-out allows backend retry) | Already covered by `test_phase3.py::test_customer_opted_out_allows_backend_retry` |

---

## 4. Decision Engine Playbooks (`src/decision_engine.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-DE-01** | Playbook Actions | Bank timeout multi-step playbook | `root_cause=bank_timeout`, `index=0, 1` | `smart_retry`, `payment_link` | Already covered by `test_phase2.py::test_all_playbook_sequences` |
| **ECP-DE-02** | Playbook Actions | NSF multi-step playbook | `root_cause=nsf`, `index=0, 1` | `delayed_retry`, `payment_link` | Already covered by `test_phase2.py::test_all_playbook_sequences` |
| **ECP-DE-03** | Playbook Actions | Immediate escalation playbook (empty list) | `root_cause=chronic_non_payer`, `index=0` | `None` | Already covered by `test_phase2.py::test_chronic_non_payer_returns_none` |
| **ECP-DE-04** | Playbook Actions | B2B Promise to Pay Missed 3-step playbook | `root_cause=promise_to_pay_missed`, `index=0, 1, 2` | `reminder`, `payment_link`, `escalate_to_collections` | **MISSING** — Added in Phase 4 |
| **ECP-DE-05** | Out-of-Bounds | Out of bounds index beyond playbook length | `root_cause=bank_timeout`, `index=5` | `None` | Already covered by `test_phase2.py::test_all_playbook_sequences` |
| **ECP-DE-06** | Invalid Cause | Unmapped / invalid root cause string | `root_cause="system_outage"`, `index=0` | `None` | Already covered by `test_phase2.py::test_invalid_and_unknown_root_causes` |

---

## 5. Reconciliation Engine (`src/reconciliation.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-RC-01** | Payment Status | Confirmed payment capture | `forced_status="CAPTURED"` | `status="reconciled"`, `new_status=RECOVERED` | Already covered by `test_phase10.py::test_reconciliation_updates_status_to_recovered` |
| **ECP-RC-02** | Payment Status | Payment authorized pending capture | `forced_status="AUTHORIZED"` | `status="authorized_pending_capture"`, `is_recovered=False` | **MISSING** (Direct unit test) — Added in Phase 4 |
| **ECP-RC-03** | Payment Status | Confirmed payment failure with auto-resume | `forced_status="FAILED"`, `auto_resume=True` | `status="reconciled_failed"`, resumes workflow | **MISSING** — Added in Phase 4 |
| **ECP-RC-04** | Monotonicity | Terminal state preserved on subsequent event | `current_status=RECOVERED`, `forced_status="FAILED"` | `status="already_recovered"`, preserves `RECOVERED` | Already covered by `test_phase10.py::test_monotonic_state_invariant` |
| **ECP-RC-05** | Non-existent Risk | Risk ID not found in database | `risk_id="risk_non_existent_999"` | `{"status": "not_found", "risk_id": ...}` | **MISSING** — Added in Phase 4 |

---

## 6. B2B Receivables Recovery (`src/receivables.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-B2B-01** | Feature Flag | Feature disabled (`B2B_ENABLED=False`) | `B2B_ENABLED=False` | Raises `PermissionError` | **MISSING** (Direct unit test) — Added in Phase 4 |
| **ECP-B2B-02** | Priority Override | Enterprise tier high priority override | `amount_due=4000.0`, `tier="ENTERPRISE"` | `Priority.HIGH` (amount < 10k, but tier=ENTERPRISE) | **MISSING** — Added in Phase 4 |
| **ECP-B2B-03** | Aging Calc | Overdue days auto-calculated when omitted | `days_overdue=None`, `due_date=now - 20 days` | Auto-calculates `days_overdue=20` | **MISSING** — Added in Phase 4 |
| **ECP-B2B-04** | Chronic Tier | Explicit chronic customer tier | `days_overdue=30`, `tier="CHRONIC_NON_PAYER"` | `RootCauseEnum.CHRONIC_NON_PAYER` | **MISSING** — Added in Phase 4 |
| **ECP-B2B-05** | P2P Status | Missed Promise-to-Pay date | `p2p_date = now - 5 days` | `RootCauseEnum.PROMISE_TO_PAY_MISSED` | Already covered by `test_phase12.py::test_overdue_detection` |

---

## 7. Customer Information Clarification (`src/info_gathering.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-INFO-01**| Customer Response | Keyword match: NSF | `text="mere account me low balance hai"` | `RootCauseEnum.NSF` | Already covered by `test_phase13.py::test_parse_customer_response` |
| **ECP-INFO-02**| Customer Response | Keyword match: Bank Timeout | `text="bank technical error otp delay"` | `RootCauseEnum.BANK_TIMEOUT` | Already covered by `test_phase13.py::test_parse_customer_response` |
| **ECP-INFO-03**| Customer Response | Empty or non-string customer response | `text=""`, `text=None` | `None` | **MISSING** — Added in Phase 4 |
| **ECP-INFO-04**| Eligibility | Non-existent risk event | `risk_id="risk_ghost_001"` | `{"eligible": False, "reason": "risk_event_not_found"}` | **MISSING** — Added in Phase 4 |
| **ECP-INFO-05**| Eligibility | Already escalated transaction | `risk_event.status=ESCALATED` | `{"eligible": False, "reason": "already_escalated"}` | **MISSING** — Added in Phase 4 |
| **ECP-INFO-06**| Clarification Cap | Second clarification attempt on same transaction | Repeated `request_customer_info()` | Blocked: `info_gathering_attempt_limit_exceeded` | Already covered by `test_phase13.py::test_second_clarification_attempt_blocked` |

---

## 8. Voice Recovery Engine (`src/voice.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-VOICE-01**| Phone Format | Non-string / invalid phone parameter | `phone_number=None`, `phone_number=12345` | `{"eligible": False, "reason": "invalid_phone_number"}` | **MISSING** — Added in Phase 4 |
| **ECP-VOICE-02**| Phone Format | Formatted phone with country code & punctuation | `phone_number="+91 (987) 654-3210"` | `{"eligible": True, "reason": "PASS"}` | **MISSING** — Added in Phase 4 |
| **ECP-VOICE-03**| Risk Status | Non-existent risk event | `risk_id="risk_voice_ghost"` | `{"eligible": False, "reason": "risk_event_not_found"}` | **MISSING** — Added in Phase 4 |
| **ECP-VOICE-04**| Risk Status | Invalid risk event status for voice outreach | `status=FAILED` | `{"eligible": False, "reason": "invalid_event_status"}` | **MISSING** — Added in Phase 4 |
| **ECP-VOICE-05**| Root Cause | Human-only chronic non-payer case | `root_cause=CHRONIC_NON_PAYER` | `{"eligible": False, "reason": "human_escalation_required"}` | **MISSING** — Added in Phase 4 |
| **ECP-VOICE-06**| Intent NLP | Ambiguous / unsupported voice transcript | `transcript="aaj mausam kaisa hai"` | Safe default to `VoiceIntent.SPEAK_TO_HUMAN` | **MISSING** — Added in Phase 4 |

---

## 9. Webhook Processing & Provenance (`src/webhook.py`)

| ID | Input Domain | Equivalence Class | Representative Input | Expected Result | Existing Coverage |
|---|---|---|---|---|---|
| **ECP-WH-01** | Signature | Valid HMAC-SHA256 signature | Signature matches body & secret | Processed successfully | Already covered by `test_phase10.py::test_webhook_deduplication` |
| **ECP-WH-02** | Signature | Invalid signature | Signature mismatch | Raises `ValueError("Invalid webhook signature")` | Already covered by `test_phase10.py::test_webhook_invalid_signature_raises` |
| **ECP-WH-03** | Signature | Missing signature header | `headers={}` | Raises `ValueError("Invalid webhook signature")` | **MISSING** — Added in Phase 4 |
| **ECP-WH-04** | Payload Body | Malformed non-JSON raw body | `raw_body="invalid_json{payload"` | Raises `ValueError("Invalid JSON webhook payload")` | **MISSING** — Added in Phase 4 |
| **ECP-WH-05** | Idempotency | Duplicate event ID receipt | Event ID already in `webhook_events` | Returns `status="duplicate_skipped"` | Already covered by `test_phase10.py::test_webhook_deduplication` |
| **ECP-WH-06** | Provenance | Provenance in `order.entity.receipt` | `{"payload": {"order": {"entity": {"receipt": "risk_rcpt_123"}}}}` | Extracts `"risk_rcpt_123"` | **MISSING** — Added in Phase 4 |
| **ECP-WH-07** | Provenance | Provenance in `payment_link.entity.reference_id` | `{"payload": {"payment_link": {"entity": {"reference_id": "risk_plink_456"}}}}` | Extracts `"risk_plink_456"` | **MISSING** — Added in Phase 4 |
| **ECP-WH-08** | Provenance | Missing / unreferenced webhook payload | Valid JSON without `risk_` reference | Extracts `None` (unattributed) | **MISSING** — Added in Phase 4 |
