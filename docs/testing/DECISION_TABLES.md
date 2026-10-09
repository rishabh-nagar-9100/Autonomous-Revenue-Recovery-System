# Decision Table Testing Specification

**Autonomous Revenue Recovery System — Software Testing FT3**  
**Technique**: Decision Table Testing (Specification-Based Multi-Condition Combinatorial Design)  
**Target Modules**: `src/guardrails.py`, `src/decision_engine.py`, `src/root_cause.py`, `src/reconciliation.py`, `src/receivables.py`

---

## 1. Overview & Methodology

Decision Table Testing is a black-box test design technique that captures complex business logic governed by combinations of inputs (Conditions) and resulting system behaviors (Actions). While Cause-Effect Graphing diagrams logical flow, Decision Tables provide an exhaustive tabular representation showing **rule precedence**, **masking effects**, and **combinational boundaries**.

### Notation
- **$T$**: Condition is Evaluated as **True**
- **$F$**: Condition is Evaluated as **False**
- **$-$**: **Don't Care** (Condition value does not influence outcome due to short-circuiting or priority masking)
- **$X$**: Action is Executed

---

## 2. Guardrails Decision Table (`src/guardrails.py`)

The Guardrails subsystem enforces strict deterministic safety and regulatory policies. The evaluation follows a rigorous priority hierarchy where higher-priority rules suppress lower-priority violations.

### 2.1 Conditions
- **$C_1$**: `attempt_number > 4` (`MAX_RETRY_ATTEMPTS`)
- **$C_2$**: `is_mandate == True` (RBI e-mandate transaction)
- **$C_3$**: `mandate_notice_served == True` (Pre-debit notice served)
- **$C_4$**: `action_type in RETRY_ACTIONS` (`{SMART_RETRY, DELAYED_RETRY}`)
- **$C_5$**: `last_retry_at is not None` and `elapsed < 14400s` (4h cooldown active)
- **$C_6$**: `action_type in CUSTOMER_FACING_ACTIONS` (`{PAYMENT_LINK, REMINDER, DISCOUNT_NUDGE}`)
- **$C_7$**: `hour < 9 or hour >= 20` (Outside 09:00–20:00, DND active)
- **$C_8$**: `customer_opted_out == True`
- **$C_9$**: `amount > 50000.0` (Exceeds human approval threshold)

### 2.2 Actions
- **$A_1$**: `BLOCK: retry_cap_exceeded`
- **$A_2$**: `BLOCK: mandate_notice_required`
- **$A_3$**: `BLOCK: cooldown_active`
- **$A_4$**: `BLOCK: dnd_hours`
- **$A_5$**: `BLOCK: customer_opted_out`
- **$A_6$**: `BLOCK: amount_requires_human_approval`
- **$A_7$**: `ALLOW: Guardrail Passed`

### 2.3 Priority Decision Table

| Condition / Rule | DT-G01 | DT-G02 | DT-G03 | DT-G04 | DT-G05 | DT-G06 | DT-G07 | DT-G08 | DT-G09 | DT-G10 | DT-G11 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **$C_1$** (Attempt $> 4$) | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **$C_2$** (Mandate) | $-$ | **T** | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **T** | **F** |
| **$C_3$** (Notice Served) | $-$ | **F** | **T** | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **F** | $-$ |
| **$C_4$** (Retry Action) | $-$ | **T** | **T** | **T** | **F** | **F** | $-$ | **T** | **T** | **F** | **F** |
| **$C_5$** (Cooldown Active) | $-$ | $-$ | **T** | **T** | $-$ | $-$ | **F** | **F** | **F** | $-$ | $-$ |
| **$C_6$** (Customer-Facing) | $-$ | $-$ | $-$ | **F** | **T** | **T** | $-$ | **F** | **F** | **T** | **T** |
| **$C_7$** (DND Active) | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **F** | **T** | **F** | **F** | **F** |
| **$C_8$** (Opted Out) | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | $-$ | **T** | **F** | **F** |
| **$C_9$** (Amount $> 50k$) | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **F** | **F** | **F** |
| **Action** | | | | | | | | | | | |
| **$A_1$** (`retry_cap_exceeded`) | **X** | | | | | | | | | | |
| **$A_2$** (`mandate_notice_required`) | | **X** | | | | | | | | | |
| **$A_3$** (`cooldown_active`) | | | **X** | **X** | | | | | | | |
| **$A_4$** (`dnd_hours`) | | | | | **X** | | | | | | |
| **$A_5$** (`customer_opted_out`) | | | | | | **X** | | | | | |
| **$A_6$** (`amount_requires_human_approval`) | | | | | | | **X** | | | | |
| **$A_7$** (`ALLOW / PASS`) | | | | | | | | **X** | **X** | **X** | **X** |

#### Priority Explanation:
- **DT-G01**: Attempt count $> 4$ suppresses all subsequent rules (Mandate, Cooldown, DND, Opt-out, Amount).
- **DT-G02**: Unserved mandate notice blocks retry action, masking cooldown, DND, and amount limits.
- **DT-G03**: Mandate notice served allows evaluation to proceed to Rule 3 (cooldown), which blocks.
- **DT-G04**: Retry action within 4h cooldown blocks regardless of time of day or customer opt-out.
- **DT-G05**: Customer-facing action during DND window (21:00) blocks, masking opt-out and amount checks.
- **DT-G06**: Customer-facing action during daytime with opted-out customer blocks.
- **DT-G07**: Amount $> 50k$ blocks with human approval requirement when all operational checks pass.
- **DT-G08**: Backend retry action (`SMART_RETRY`) is immune to DND hours and allowed.
- **DT-G09**: Backend retry action is immune to customer opt-out and allowed.
- **DT-G10**: Mandate without notice does NOT block non-retry action (`PAYMENT_LINK`) and allowed.
- **DT-G11**: All guardrail conditions satisfied allows standard customer action.

---

## 3. Root Cause & Decision Engine Playbook Table (`src/root_cause.py` & `src/decision_engine.py`)

The Root Cause Engine maps incoming error signals and metadata into discrete root causes, while the Decision Engine maps those causes to deterministic playbook actions.

### 3.1 Conditions
- **$C_1$**: Chronic indicator (`consecutive_failures >= 4` OR `is_chronic_defaulter == True` OR `customer_risk_profile == 'chronic_non_payer'`)
- **$C_2$**: `error_reason in BANK_TIMEOUT_REASONS` OR `error_code in BANK_TIMEOUT_CODES`
- **$C_3$**: `error_reason in NSF_REASONS` OR `error_code in NSF_CODES`
- **$C_4$**: `error_reason in EXPIRED_CARD_REASONS` OR `error_code in EXPIRED_CARD_CODES`
- **$C_5$**: `event_type == 'cart_abandonment'` OR cart error reason/code
- **$C_6$**: `event_type == 'recent_overdue'` OR overdue error reason/code
- **$C_7$**: `action_index` ($0, 1, 2$)

### 3.2 Actions
- **$A_1$**: Root Cause: `CHRONIC_NON_PAYER`, Next Action: `None` (Escalate immediately)
- **$A_2$**: Root Cause: `BANK_TIMEOUT`, Next Action: `smart_retry` (Index 0)
- **$A_3$**: Root Cause: `BANK_TIMEOUT`, Next Action: `payment_link` (Index 1)
- **$A_4$**: Root Cause: `BANK_TIMEOUT`, Next Action: `None` (Playbook exhausted)
- **$A_5$**: Root Cause: `NSF`, Next Action: `delayed_retry` (Index 0)
- **$A_6$**: Root Cause: `NSF`, Next Action: `payment_link` (Index 1)
- **$A_7$**: Root Cause: `EXPIRED_CARD`, Next Action: `payment_link` (Index 0)
- **$A_8$**: Root Cause: `EXPIRED_CARD`, Next Action: `reminder` (Index 1)
- **$A_9$**: Root Cause: `CART_ABANDONMENT`, Next Action: `discount_nudge` (Index 0)
- **$A_{10}$**: Root Cause: `RECENT_OVERDUE`, Next Action: `reminder` (Index 0)
- **$A_{11}$**: Root Cause: `UNKNOWN`, Next Action: `None` (Unmapped / no playbook)

### 3.3 Root Cause & Playbook Decision Table

| Condition / Rule | DT-R01 | DT-R02 | DT-R03 | DT-R04 | DT-R05 | DT-R06 | DT-R07 | DT-R08 | DT-R09 | DT-R10 | DT-R11 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **$C_1$** (Chronic Indicator) | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **$C_2$** (Bank Timeout) | $-$ | **T** | **T** | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **$C_3$** (NSF) | $-$ | $-$ | $-$ | $-$ | **T** | **T** | **F** | **F** | **F** | **F** | **F** |
| **$C_4$** (Expired Card) | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **T** | **F** | **F** | **F** |
| **$C_5$** (Cart Abandonment) | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **F** |
| **$C_6$** (Recent Overdue) | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** |
| **$C_7$** (Action Index) | **0** | **0** | **1** | **2** | **0** | **1** | **0** | **1** | **0** | **0** | **0** |
| **Action** | | | | | | | | | | | |
| **$A_1$** (`CHRONIC_NON_PAYER -> None`) | **X** | | | | | | | | | | |
| **$A_2$** (`BANK_TIMEOUT -> smart_retry`) | | **X** | | | | | | | | | |
| **$A_3$** (`BANK_TIMEOUT -> payment_link`) | | | **X** | | | | | | | |
| **$A_4$** (`BANK_TIMEOUT -> None`) | | | | **X** | | | | | | |
| **$A_5$** (`NSF -> delayed_retry`) | | | | | **X** | | | | | |
| **$A_6$** (`NSF -> payment_link`) | | | | | | **X** | | | | |
| **$A_7$** (`EXPIRED_CARD -> payment_link`) | | | | | | | **X** | | | |
| **$A_8$** (`EXPIRED_CARD -> reminder`) | | | | | | | | **X** | | |
| **$A_9$** (`CART_ABANDONMENT -> discount_nudge`) | | | | | | | | | **X** | |
| **$A_{10}$** (`RECENT_OVERDUE -> reminder`) | | | | | | | | | | **X** |
| **$A_{11}$** (`UNKNOWN -> None`) | | | | | | | | | | | **X** |

---

## 4. Payment Reconciliation Decision Table (`src/reconciliation.py`)

The Reconciliation Engine arbitrates payment verification events, enforces terminal monotonicity, and handles automated polling timeouts.

### 4.1 Conditions
- **$C_1$**: `current_status == 'RECOVERED'` (Terminal Monotonic Invariant)
- **$C_2$**: `reconciled_status in {'RECOVERED', 'SUCCESS', 'CAPTURED'}`
- **$C_3$**: `reconciled_status in {'AUTHORIZED', 'payment.authorized'}`
- **$C_4$**: `reconciled_status == 'FAILED'`
- **$C_5$**: `auto_resume == True`
- **$C_6$**: `attempt_count >= 3` (`MAX_RECONCILIATION_ATTEMPTS`)
- **$C_7$**: `elapsed_hours >= 24.0` (`MAX_RECONCILIATION_HOURS`)

### 4.2 Actions
- **$A_1$**: Return `already_recovered` (no DB mutation, audit logged)
- **$A_2$**: Transition to `RECOVERED` (record outcome with amount)
- **$A_3$**: Return `authorized_pending_capture` (remain not recovered)
- **$A_4$**: Transition to `IN_PROGRESS` + resume recovery workflow
- **$A_5$**: Transition to `IN_PROGRESS` without auto-resume
- **$A_6$**: Transition to `ESCALATED` (`escalated_timeout`, open escalation recorded)
- **$A_7$**: Return `pending_reconciliation` (polling continues)

### 4.3 Reconciliation Decision Table

| Condition / Rule | DT-M01 | DT-M02 | DT-M03 | DT-M04 | DT-M05 | DT-M06 | DT-M07 | DT-M08 | DT-M09 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **$C_1$** (Current `RECOVERED`) | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **$C_2$** (Status Success/Captured) | $-$ | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **$C_3$** (Status Authorized) | $-$ | $-$ | **T** | **F** | **F** | **F** | **F** | **F** | **F** |
| **$C_4$** (Status Failed) | $-$ | $-$ | $-$ | **T** | **T** | **F** | **F** | **F** | **F** |
| **$C_5$** (Auto-Resume) | $-$ | $-$ | $-$ | **T** | **F** | $-$ | $-$ | $-$ | $-$ |
| **$C_6$** (Attempts $\ge 3$) | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **T** | **F** |
| **$C_7$** (Elapsed Hours $\ge 24$) | $-$ | $-$ | $-$ | $-$ | $-$ | **F** | **T** | **T** | **F** |
| **Action** | | | | | | | | | |
| **$A_1$** (`already_recovered`) | **X** | | | | | | | | |
| **$A_2$** (`reconciled -> RECOVERED`) | | **X** | | | | | | | |
| **$A_3$** (`authorized_pending_capture`) | | | **X** | | | | | | |
| **$A_4$** (`reconciled_failed + auto_resume`) | | | | **X** | | | | |
| **$A_5$** (`reconciled_failed`) | | | | | **X** | | | |
| **$A_6$** (`escalated_timeout`) | | | | | | **X** | **X** | **X** | |
| **$A_7$** (`pending_reconciliation`) | | | | | | | | | **X** |

---

## 5. B2B Receivables Recovery Decision Table (`src/receivables.py`)

The B2B Receivables engine assesses commercial invoices, payment promises, and customer credit profiles.

### 5.1 Conditions
- **$C_1$**: `is_b2b_enabled() == True` (`B2B_ENABLED=true`)
- **$C_2$**: `promise_to_pay_date is not None` and `ref_time > promise_to_pay_date` (P2P missed)
- **$C_3$**: `customer_tier == 'CHRONIC_NON_PAYER'`
- **$C_4$**: `days_overdue > 90`
- **$C_5$**: `amount_due >= 10000.0`
- **$C_6$**: `customer_tier == 'ENTERPRISE'`

### 5.2 Actions
- **$A_1$**: Raise `PermissionError` (B2B disabled)
- **$A_2$**: Root Cause `PROMISE_TO_PAY_MISSED`, Priority `HIGH`, Status `RECOVERED`
- **$A_3$**: Root Cause `PROMISE_TO_PAY_MISSED`, Priority `MEDIUM`, Status `RECOVERED`
- **$A_4$**: Root Cause `CHRONIC_NON_PAYER`, Priority `HIGH`, Status `ESCALATED`
- **$A_5$**: Root Cause `CHRONIC_NON_PAYER`, Priority `MEDIUM`, Status `ESCALATED`
- **$A_6$**: Root Cause `RECEIVABLE_OVERDUE`, Priority `HIGH`, Status `RECOVERED`
- **$A_7$**: Root Cause `RECEIVABLE_OVERDUE`, Priority `MEDIUM`, Status `RECOVERED`

### 5.3 B2B Receivables Decision Table

| Condition / Rule | DT-B01 | DT-B02 | DT-B03 | DT-B04 | DT-B05 | DT-B06 | DT-B07 | DT-B08 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **$C_1$** (B2B Enabled) | **F** | **T** | **T** | **T** | **T** | **T** | **T** | **T** |
| **$C_2$** (P2P Missed) | $-$ | **T** | **T** | **F** | **F** | **F** | **F** | **F** |
| **$C_3$** (Chronic Tier) | $-$ | **T** | $-$ | **T** | **F** | **F** | **F** | **F** |
| **$C_4$** (Days Overdue $> 90$) | $-$ | **T** | $-$ | $-$ | **T** | **F** | **F** | **F** |
| **$C_5$** (Amount $\ge 10k$) | $-$ | **T** | **F** | **T** | **F** | **F** | **T** | **F** |
| **$C_6$** (Enterprise Tier) | $-$ | $-$ | **F** | $-$ | **F** | **T** | **F** | **F** |
| **Action** | | | | | | | | |
| **$A_1$** (`PermissionError`) | **X** | | | | | | | |
| **$A_2$** (`P2P Missed / High / RECOVERED`) | | **X** | | | | | | |
| **$A_3$** (`P2P Missed / Med / RECOVERED`) | | | **X** | | | | | |
| **$A_4$** (`Chronic / High / ESCALATED`) | | | | **X** | | | | |
| **$A_5$** (`Chronic / Med / ESCALATED`) | | | | | **X** | | | |
| **$A_6$** (`Standard / High / RECOVERED`) | | | | | | **X** | **X** | |
| **$A_7$** (`Standard / Med / RECOVERED`) | | | | | | | | **X** |

---

## 6. Summary of Decision Rules

- **Total Decision Tables**: 4 tables
- **Total Unique Conditions Analyzed**: 29 conditions
- **Total Decision Rules Specified**: 39 rules
  - Guardrails: 11 rules (DT-G01 to DT-G11)
  - Root Cause & Playbook: 11 rules (DT-R01 to DT-R11)
  - Payment Reconciliation: 9 rules (DT-M01 to DT-M09)
  - B2B Receivables: 8 rules (DT-B01 to DT-B08)
