# Decision Table Traceability Matrix

**Autonomous Revenue Recovery System — Software Testing FT3**  
**Document**: `docs/testing/DECISION_TABLE_TEST_MATRIX.md`

---

## 1. Traceability Overview

This matrix maps every decision rule from `docs/testing/DECISION_TABLES.md` directly to its corresponding automated test case in `tests/ft3/test_decision_tables.py`, along with cross-references to existing tests from prior testing phases (Baseline, BVA, ECP, Cause-Effect Graphing).

| Table Identifier | Subsystem Module | Rules Count | Test Coverage Type |
| :--- | :--- | :---: | :--- |
| **DT-G** | Guardrails Priority Hierarchy | 11 | Parameterized Automated Tests + Cross-Phase Verification |
| **DT-R** | Root Cause & Playbook Selection | 11 | Parameterized Automated Tests + Cross-Phase Verification |
| **DT-M** | Reconciliation State Machine | 9 | Parameterized Automated Tests + Cross-Phase Verification |
| **DT-B** | B2B Receivables Recovery | 8 | Parameterized Automated Tests + Cross-Phase Verification |
| **TOTAL** | — | **39 Rules** | **100% Traceability to Automated Tests** |

---

## 2. Complete Traceability Mapping

| Rule ID | Module | Conditions Evaluated | Expected Result | Primary Automated Test ID | Existing / New | Cross-Reference Tests |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **DT-G01** | `src/guardrails.py` | Attempt $> 4$, all other conditions True/False | `BLOCK: retry_cap_exceeded` | `test_dt_guardrails_rules[DT-G01]` | **New** | `test_ceg_g01`, `test_attempt_number_5_blocked_with_retry_cap_exceeded` |
| **DT-G02** | `src/guardrails.py` | Attempt $\le 4$, Mandate=T, Notice=F, Action=Retry, Cooldown=T, DND=T, OptOut=T | `BLOCK: mandate_notice_required` | `test_dt_guardrails_rules[DT-G02]` | **New** | `test_ceg_g03`, `test_mandate_without_notice_blocks_retry` |
| **DT-G03** | `src/guardrails.py` | Mandate=T, Notice=T, Action=Retry, Cooldown=T (1h elapsed), Daytime | `BLOCK: cooldown_active` | `test_dt_guardrails_rules[DT-G03]` | **New** | `test_ceg_g02`, `test_mandate_with_notice_served_passes` |
| **DT-G04** | `src/guardrails.py` | Non-mandate, Action=Retry, Cooldown=T (1h elapsed), Daytime, OptOut=T | `BLOCK: cooldown_active` | `test_dt_guardrails_rules[DT-G04]` | **New** | `test_ceg_g04`, `test_cooldown_active_blocks_retry_within_4_hours` |
| **DT-G05** | `src/guardrails.py` | Action=CustomerFacing (Link), Night hour (22:00 DND), OptOut=T, Amount $> 50k$ | `BLOCK: dnd_hours` | `test_dt_guardrails_rules[DT-G05]` | **New** | `test_ceg_g06`, `test_ceg_g09`, `test_customer_facing_action_during_night_dnd_is_blocked` |
| **DT-G06** | `src/guardrails.py` | Action=CustomerFacing (Reminder), Daytime (14:00), OptOut=T, Amount $> 50k$ | `BLOCK: customer_opted_out` | `test_dt_guardrails_rules[DT-G06]` | **New** | `test_ceg_g08`, `test_customer_opted_out_blocks_customer_facing_action` |
| **DT-G07** | `src/guardrails.py` | Action=CustomerFacing (Link), Daytime (14:00), OptOut=F, Amount $= 75k > 50k$ | `BLOCK: amount_requires_human_approval` | `test_dt_guardrails_rules[DT-G07]` | **New** | `test_ceg_g10`, `test_amount_above_threshold_is_blocked` |
| **DT-G08** | `src/guardrails.py` | Action=Retry (`SMART_RETRY`), Cooldown=F, Night hour (23:00 DND), Amount $< 50k$ | `ALLOW: PASS (DND Immunity)` | `test_dt_guardrails_rules[DT-G08]` | **New** | `test_ceg_g07`, `test_backend_smart_retry_allowed_during_dnd_hours` |
| **DT-G09** | `src/guardrails.py` | Action=Retry (`SMART_RETRY`), Cooldown=F, Daytime, OptOut=T, Amount $< 50k$ | `ALLOW: PASS (Opt-out Immunity)` | `test_dt_guardrails_rules[DT-G09]` | **New** | `test_ceg_g08`, `test_customer_opted_out_allows_backend_retry` |
| **DT-G10** | `src/guardrails.py` | Mandate=T, Notice=F, Action=CustomerFacing (`PAYMENT_LINK`), Daytime | `ALLOW: PASS (Notice Bypass)` | `test_dt_guardrails_rules[DT-G10]` | **New** | `test_ceg_g02` |
| **DT-G11** | `src/guardrails.py` | All constraints clean, CustomerFacing, Daytime, OptOut=F, Amount $< 50k$ | `ALLOW: PASS (Clean Execution)` | `test_dt_guardrails_rules[DT-G11]` | **New** | `test_ceg_g11`, `test_customer_facing_action_inside_allowed_hours_passes` |
| **DT-R01** | `src/root_cause.py` & `src/decision_engine.py` | Consecutive failures $\ge 4$, Gateway timeout code present, Index 0 | Root Cause: `CHRONIC_NON_PAYER`, Action: `None` | `test_dt_root_cause_playbook_rules[DT-R01]` | **New** | `test_ceg_c01`, `test_chronic_non_payer_returns_none_immediately` |
| **DT-R02** | `src/root_cause.py` & `src/decision_engine.py` | Bank timeout error code, Non-chronic, Index 0 | Root Cause: `BANK_TIMEOUT`, Action: `smart_retry` | `test_dt_root_cause_playbook_rules[DT-R02]` | **New** | `test_ceg_c03`, `test_all_playbook_sequences[bank_timeout]` |
| **DT-R03** | `src/root_cause.py` & `src/decision_engine.py` | Bank timeout error code, Non-chronic, Index 1 | Root Cause: `BANK_TIMEOUT`, Action: `payment_link` | `test_dt_root_cause_playbook_rules[DT-R03]` | **New** | `test_ceg_c03`, `test_all_playbook_sequences[bank_timeout]` |
| **DT-R04** | `src/root_cause.py` & `src/decision_engine.py` | Bank timeout error code, Non-chronic, Index 2 | Root Cause: `BANK_TIMEOUT`, Action: `None` | `test_dt_root_cause_playbook_rules[DT-R04]` | **New** | `test_scenario_2_bank_timeout_all_failed_playbook_exhausted` |
| **DT-R05** | `src/root_cause.py` & `src/decision_engine.py` | NSF error reason, Non-chronic, Index 0 | Root Cause: `NSF`, Action: `delayed_retry` | `test_dt_root_cause_playbook_rules[DT-R05]` | **New** | `test_ceg_c04`, `test_all_playbook_sequences[nsf]` |
| **DT-R06** | `src/root_cause.py` & `src/decision_engine.py` | NSF error reason, Non-chronic, Index 1 | Root Cause: `NSF`, Action: `payment_link` | `test_dt_root_cause_playbook_rules[DT-R06]` | **New** | `test_ceg_c04`, `test_all_playbook_sequences[nsf]` |
| **DT-R07** | `src/root_cause.py` & `src/decision_engine.py` | Card expired error reason, Non-chronic, Index 0 | Root Cause: `EXPIRED_CARD`, Action: `payment_link` | `test_dt_root_cause_playbook_rules[DT-R07]` | **New** | `test_ceg_c05`, `test_all_playbook_sequences[expired_card]` |
| **DT-R08** | `src/root_cause.py` & `src/decision_engine.py` | Card expired error reason, Non-chronic, Index 1 | Root Cause: `EXPIRED_CARD`, Action: `reminder` | `test_dt_root_cause_playbook_rules[DT-R08]` | **New** | `test_ceg_c05`, `test_all_playbook_sequences[expired_card]` |
| **DT-R09** | `src/root_cause.py` & `src/decision_engine.py` | Cart abandonment event type, Index 0 | Root Cause: `CART_ABANDONMENT`, Action: `discount_nudge` | `test_dt_root_cause_playbook_rules[DT-R09]` | **New** | `test_all_playbook_sequences[cart_abandonment]` |
| **DT-R10** | `src/root_cause.py` & `src/decision_engine.py` | Recent overdue event type, Index 0 | Root Cause: `RECENT_OVERDUE`, Action: `reminder` | `test_dt_root_cause_playbook_rules[DT-R10]` | **New** | `test_all_playbook_sequences[recent_overdue]` |
| **DT-R11** | `src/root_cause.py` & `src/decision_engine.py` | Unrecognized error reason and code, Index 0 | Root Cause: `UNKNOWN`, Action: `None` | `test_dt_root_cause_playbook_rules[DT-R11]` | **New** | `test_ceg_c06`, `test_invalid_and_unknown_root_causes` |
| **DT-M01** | `src/reconciliation.py` | Current status `RECOVERED`, Inbound status `SUCCESS` or `FAILED` | Return `already_recovered` (terminal lock) | `test_dt_reconciliation_rules[DT-M01]` | **New** | `test_ceg_m01` |
| **DT-M02** | `src/reconciliation.py` | Current status `IN_PROGRESS`, Inbound status `CAPTURED` | Transition to `RECOVERED`, Record Outcome | `test_dt_reconciliation_rules[DT-M02]` | **New** | `test_ceg_m02` |
| **DT-M03** | `src/reconciliation.py` | Current status `IN_PROGRESS`, Inbound status `AUTHORIZED` | Return `authorized_pending_capture`, remain NOT RECOVERED | `test_dt_reconciliation_rules[DT-M03]` | **New** | `test_ceg_m03` |
| **DT-M04** | `src/reconciliation.py` | Current status `DETECTED`, Inbound status `FAILED`, auto_resume=T | Transition to `IN_PROGRESS`, Resume Workflow | `test_dt_reconciliation_rules[DT-M04]` | **New** | `test_ceg_m04` |
| **DT-M05** | `src/reconciliation.py` | Current status `DETECTED`, Inbound status `FAILED`, auto_resume=F | Transition to `IN_PROGRESS`, Workflow Not Resumed | `test_dt_reconciliation_rules[DT-M05]` | **New** | `test_ceg_m04` |
| **DT-M06** | `src/reconciliation.py` | Status `PENDING`, Attempts $= 3 \ge 3$, Elapsed hours $= 2.0 < 24$ | Transition to `ESCALATED` (`escalated_timeout`) | `test_dt_reconciliation_rules[DT-M06]` | **New** | `test_ceg_m05` |
| **DT-M07** | `src/reconciliation.py` | Status `PENDING`, Attempts $= 1 < 3$, Elapsed hours $= 24.5 \ge 24$ | Transition to `ESCALATED` (`escalated_timeout`) | `test_dt_reconciliation_rules[DT-M07]` | **New** | `test_ceg_m06` |
| **DT-M08** | `src/reconciliation.py` | Status `PENDING`, Attempts $= 4 \ge 3$, Elapsed hours $= 25.0 \ge 24$ | Transition to `ESCALATED` (`escalated_timeout`) | `test_dt_reconciliation_rules[DT-M08]` | **New** | `test_ceg_m05`, `test_ceg_m06` |
| **DT-M09** | `src/reconciliation.py` | Status `PENDING`, Attempts $= 2 < 3$, Elapsed hours $= 12.0 < 24$ | Return `pending_reconciliation` | `test_dt_reconciliation_rules[DT-M09]` | **New** | `test_ceg_m07` |
| **DT-B01** | `src/receivables.py` | `B2B_ENABLED=false` | Raise `PermissionError` | `test_dt_b2b_receivables_rules[DT-B01]` | **New** | `test_ceg_b01`, `test_b2b_feature_flag_disabled_rejects` |
| **DT-B02** | `src/receivables.py` | `B2B_ENABLED=true`, Missed P2P date, Chronic tier, Overdue 100 days, Amount $15k$ | `PROMISE_TO_PAY_MISSED`, Priority `HIGH`, Status `RECOVERED` | `test_dt_b2b_receivables_rules[DT-B02]` | **New** | `test_ceg_b02` |
| **DT-B03** | `src/receivables.py` | `B2B_ENABLED=true`, Missed P2P date, Standard tier, Overdue 10 days, Amount $5k$ | `PROMISE_TO_PAY_MISSED`, Priority `MEDIUM`, Status `RECOVERED` | `test_dt_b2b_receivables_rules[DT-B03]` | **New** | `test_ceg_b02` |
| **DT-B04** | `src/receivables.py` | `B2B_ENABLED=true`, No P2P, Chronic tier, Amount $12k$ | `CHRONIC_NON_PAYER`, Priority `HIGH`, Status `ESCALATED` | `test_dt_b2b_receivables_rules[DT-B04]` | **New** | `test_ceg_b03` |
| **DT-B05** | `src/receivables.py` | `B2B_ENABLED=true`, No P2P, Standard tier, Overdue 95 days, Amount $4k$ | `CHRONIC_NON_PAYER`, Priority `MEDIUM`, Status `ESCALATED` | `test_dt_b2b_receivables_rules[DT-B05]` | **New** | `test_ceg_b04` |
| **DT-B06** | `src/receivables.py` | `B2B_ENABLED=true`, No P2P, Enterprise tier, Overdue 15 days, Amount $5k$ | `RECEIVABLE_OVERDUE`, Priority `HIGH`, Status `RECOVERED` | `test_dt_b2b_receivables_rules[DT-B06]` | **New** | `test_ceg_b06`, `test_b2b_enterprise_tier_priority_high` |
| **DT-B07** | `src/receivables.py` | `B2B_ENABLED=true`, No P2P, Standard tier, Overdue 15 days, Amount $15k \ge 10k$ | `RECEIVABLE_OVERDUE`, Priority `HIGH`, Status `RECOVERED` | `test_dt_b2b_receivables_rules[DT-B07]` | **New** | `test_ceg_b06` |
| **DT-B08** | `src/receivables.py` | `B2B_ENABLED=true`, No P2P, Standard tier, Overdue 15 days, Amount $5k < 10k$ | `RECEIVABLE_OVERDUE`, Priority `MEDIUM`, Status `RECOVERED` | `test_dt_b2b_receivables_rules[DT-B08]` | **New** | `test_ceg_b05`, `test_ceg_b06` |
