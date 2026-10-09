# White Box Testing Analysis

**Autonomous Revenue Recovery System — Software Testing FT3**  
**Document**: `docs/testing/WHITE_BOX_ANALYSIS.md`  
**Technique**: White Box (Structural / Glass-Box) Testing  
**Targets**: Structural branch, condition, and path analysis of core recovery engines

---

## 1. Overview & Methodology

White Box Testing evaluates internal control flow structures, statement execution, decision branch outcomes, condition truth tables, and independent linear paths through source code.

### Metrics & Formulas
- **Cyclomatic Complexity ($M$)**:
  McCabe's formula:
  $$M = E - N + 2P$$
  where $E$ is the number of edges, $N$ is the number of nodes, and $P$ is the number of connected components ($P=1$ for a single function).
  Equivalently, for structured programs:
  $$M = D + 1$$
  where $D$ is the count of binary decision / predicate nodes (including Boolean operators `and`, `or` within compound expressions).

- **Coverage Criteria**:
  1. **Statement Coverage ($C_0$)**: Percentage of executable program statements exercised by tests.
  2. **Branch / Decision Coverage ($C_1$)**: Percentage of decision outcomes (True/False) exercised.
  3. **Condition Coverage ($C_2$)**: Percentage of individual Boolean sub-expressions evaluated to both True and False.
  4. **Basis Path Coverage**: Ensuring every linearly independent execution path is traversed at least once.

---

## 2. Structural Analysis of Critical Functions

### 2.1 `evaluate_guardrails` in `src/guardrails.py`
- **Module**: `src/guardrails.py`
- **Lines of Code**: Lines 62–153 (~92 lines)
- **Purpose**: Evaluates proposed recovery interventions against regulatory, customer preference, and business safety constraints in strict priority order.
- **Decision / Predicate Points ($D$)**:
  1. `ctx.attempt_number > MAX_RETRY_ATTEMPTS` (1)
  2. `ctx.is_mandate` (1)
  3. `not ctx.mandate_notice_served` (1)
  4. `action_type in RETRY_ACTIONS` (1)
  5. `ctx.last_retry_at is not None` (1)
  6. `action_type in RETRY_ACTIONS` (1)
  7. `elapsed < COOLDOWN_SECONDS` (1)
  8. `action_type in CUSTOMER_FACING_ACTIONS` (1)
  9. `current_hour < DND_START_HOUR or current_hour >= DND_END_HOUR` (2)
  10. `ctx.customer_opted_out` (1)
  11. `action_type in CUSTOMER_FACING_ACTIONS` (1)
  12. `amount > ctx.human_approval_threshold` (1)
  - **Total Predicate Nodes ($D$)**: 13
  - **Cyclomatic Complexity ($M = D + 1$)**: **14**
- **Independent Execution Paths**:
  - **Path G1**: Attempt $> 4 \to$ `BLOCK: retry_cap_exceeded`
  - **Path G2**: Mandate $\wedge \neg$Notice $\wedge$ Retry Action $\to$ `BLOCK: mandate_notice_required`
  - **Path G3**: Cooldown Active $\wedge$ Retry Action $\to$ `BLOCK: cooldown_active`
  - **Path G4**: Customer Facing $\wedge$ Outside 09:00–20:00 $\to$ `BLOCK: dnd_hours`
  - **Path G5**: Customer Facing $\wedge$ Opted Out $\to$ `BLOCK: customer_opted_out`
  - **Path G6**: Amount $> 50,000 \to$ `BLOCK: amount_requires_human_approval`
  - **Path G7**: All constraints satisfied $\to$ `PASS` (clean execution)
  - **Path G8**: Backend retry action immune to DND and opt-out $\to$ `PASS`
  - **Path G9**: Non-retry customer action on mandate without notice $\to$ `PASS`

---

### 2.2 `diagnose_root_cause_rules` in `src/root_cause.py`
- **Module**: `src/root_cause.py`
- **Lines of Code**: Lines 57–144 (~88 lines)
- **Purpose**: Tier 1 deterministic mapping of Razorpay error codes, reasons, and customer history to canonical root cause enums.
- **Decision / Predicate Points ($D$)**:
  1. `event.metadata.get("is_chronic_defaulter")` (1)
  2. `customer_risk_profile == "chronic_non_payer"` (1)
  3. `consecutive_failures >= 4` (1)
  4. `reason in BANK_TIMEOUT_REASONS or code in BANK_TIMEOUT_CODES` (2)
  5. `reason in NSF_REASONS or code in NSF_CODES` (2)
  6. `reason in EXPIRED_CARD_REASONS or code in EXPIRED_CARD_CODES` (2)
  7. `event.event_type == "cart_abandonment" or reason in cart_reasons or code in cart_codes` (3)
  8. `event.event_type == "recent_overdue" or reason in overdue_reasons or code in overdue_codes` (3)
  9. `reason in chronic_reasons or code in chronic_codes` (2)
  - **Total Predicate Nodes ($D$)**: 17
  - **Cyclomatic Complexity ($M = D + 1$)**: **18**
- **Independent Execution Paths**:
  - **Path R1**: Chronic metadata flag ($C_1 \vee C_2 \vee C_3$) $\to$ `CHRONIC_NON_PAYER`
  - **Path R2**: Bank Timeout error reason or code $\to$ `BANK_TIMEOUT`
  - **Path R3**: NSF error reason or code $\to$ `NSF`
  - **Path R4**: Expired Card error reason or code $\to$ `EXPIRED_CARD`
  - **Path R5**: Cart abandonment type/reason/code $\to$ `CART_ABANDONMENT`
  - **Path R6**: Recent overdue type/reason/code $\to$ `RECENT_OVERDUE`
  - **Path R7**: Explicit chronic reason/code in payload $\to$ `CHRONIC_NON_PAYER`
  - **Path R8**: Unmapped error signal $\to$ `UNKNOWN` (confidence 0.0)

---

### 2.3 `reconcile_payment_status` in `src/reconciliation.py`
- **Module**: `src/reconciliation.py`
- **Lines of Code**: Lines 19–297 (~279 lines)
- **Purpose**: Enforces monotonic terminal state invariants, translates webhook events, and handles automated polling timeouts.
- **Decision / Predicate Points ($D$)**:
  1. `if not row:` (1)
  2. `if current_status == EventStatus.RECOVERED.value:` (1)
  3. `if current_status == RECOVERED and forced_status == "FAILED":` (1)
  4. `if reconciled_status in {"RECOVERED", "SUCCESS", "CAPTURED"}:` (1)
  5. `if idx_row:` and `max_val is not None:` (2)
  6. `if not cursor.fetchone():` (1)
  7. `if reconciled_status in {"AUTHORIZED", "payment.authorized"}:` (1)
  8. `if reconciled_status == "FAILED":` (1)
  9. `if auto_resume:` (1)
  10. `if attempt_count >= MAX_RECONCILIATION_ATTEMPTS or elapsed_hours >= MAX_RECONCILIATION_HOURS:` (2)
  11. Audit metadata enrichment checks: `razorpay_payment_id`, `webhook_event_id` (4)
  - **Total Predicate Nodes ($D$)**: 16
  - **Cyclomatic Complexity ($M = D + 1$)**: **17**
- **Independent Execution Paths**:
  - **Path M1**: Missing risk event record $\to$ `{"status": "not_found"}`
  - **Path M2**: Monotonic terminal invariant ($current == RECOVERED$) $\to$ `{"status": "already_recovered"}`
  - **Path M3**: Successful capture $\to$ `RECOVERED` + verified outcome record
  - **Path M4**: Payment authorized $\to$ `authorized_pending_capture` (remains not recovered)
  - **Path M5**: Payment failed with `auto_resume=False` $\to$ `IN_PROGRESS`
  - **Path M6**: Payment failed with `auto_resume=True` $\to$ `IN_PROGRESS` + resume workflow
  - **Path M7**: Unresolved status with attempts $\ge 3 \to$ `ESCALATED` (`escalated_timeout`)
  - **Path M8**: Unresolved status with elapsed hours $\ge 24.0 \to$ `ESCALATED` (`escalated_timeout`)
  - **Path M9**: Unresolved status within limits $\to$ `pending_reconciliation`

---

### 2.4 `extract_reference_id` in `src/webhook.py`
- **Module**: `src/webhook.py`
- **Lines of Code**: Lines 24–100 (~77 lines)
- **Purpose**: Pure, fail-safe provenance extractor for Razorpay webhook payloads.
- **Decision / Predicate Points ($D$)**:
  1. `if not isinstance(payload, dict):` (1)
  2. `_is_valid_risk_id`: `isinstance(val, str)` and `cleaned.startswith("risk_")` (2)
  3. `_extract_from_notes`: `not isinstance(entity, dict)` (1), `isinstance(notes, dict)` (1), loop keys (1)
  4. `payment.entity.notes` check (1)
  5. `order.entity.notes` check (1)
  6. `order.entity.receipt` check (1)
  7. `payment_link.entity.reference_id` check (1)
  8. `payment_link.entity.notes` check (1)
  9. Top-level notes check (1)
  10. Top-level fallback keys loop (1)
  - **Total Predicate Nodes ($D$)**: 11
  - **Cyclomatic Complexity ($M = D + 1$)**: **12**

---

### 2.5 `handle_outcome` in `src/outcome_tracker.py`
- **Module**: `src/outcome_tracker.py`
- **Lines of Code**: Lines 60–250 (~190 lines)
- **Purpose**: Closed-loop recovery workflow state engine dispatching next actions, managing guardrail re-evaluation, and handling terminal states.
- **Decision / Predicate Points ($D$)**:
  1. `if not risk_event:` (1)
  2. `if not root_cause:` (1)
  3. `if execution_status == ExecutionStatusEnum.SUCCESS:` (1)
  4. `elif execution_status == ExecutionStatusEnum.FAILED:` (1)
  5. `if not next_act:` (playbook exhausted) (1)
  6. `if guardrail_check.result == GuardrailResultEnum.BLOCK:` (1)
  7. `if simulated_action_outcomes and ...:` (1)
  - **Total Predicate Nodes ($D$)**: 7
  - **Cyclomatic Complexity ($M = D + 1$)**: **8**

---

### 2.6 `process_b2b_receivable` in `src/receivables.py`
- **Module**: `src/receivables.py`
- **Lines of Code**: Lines 47–180 (~134 lines)
- **Purpose**: Ingestion, risk initialization, priority classification, and recovery orchestration for B2B commercial debt.
- **Decision / Predicate Points ($D$)**:
  1. `if not is_b2b_enabled():` (1)
  2. `if days_overdue is None:` (1)
  3. `amount_due >= 10000.0 or customer_tier == "ENTERPRISE"` (2)
  4. `if root_cause_enum == RootCauseEnum.CHRONIC_NON_PAYER:` (1)
  5. `if wf_result.final_status == EventStatus.IN_PROGRESS:` (1)
  6. `elif wf_result.final_status == EventStatus.ESCALATED:` (1)
  - **Total Predicate Nodes ($D$)**: 7
  - **Cyclomatic Complexity ($M = D + 1$)**: **8**

---

## 3. Summary of Function Complexity Metrics

| Module | Function | Lines of Code | Decisions ($D$) | Cyclomatic Complexity ($M$) | Risk Level |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `src/guardrails.py` | `evaluate_guardrails` | 92 | 13 | **14** | Moderate |
| `src/root_cause.py` | `diagnose_root_cause_rules` | 88 | 17 | **18** | Moderate |
| `src/reconciliation.py` | `reconcile_payment_status` | 279 | 16 | **17** | Moderate |
| `src/webhook.py` | `extract_reference_id` | 77 | 11 | **12** | Moderate |
| `src/outcome_tracker.py` | `handle_outcome` | 190 | 7 | **8** | Low |
| `src/receivables.py` | `process_b2b_receivable` | 134 | 7 | **8** | Low |
| `src/receivables.py` | `evaluate_receivable_root_cause` | 17 | 4 | **5** | Low |
| `src/voice.py` | `check_voice_eligibility` | 46 | 10 | **11** | Moderate |
| `src/info_gathering.py` | `request_customer_info` | 55 | 4 | **5** | Low |
