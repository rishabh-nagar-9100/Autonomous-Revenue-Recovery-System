# Decision Table Testing Report

**Autonomous Revenue Recovery System — Software Testing FT3**  
**Technique**: Decision Table Testing (Black-Box Multi-Condition Combinatorial Design)  
**Execution Date**: October 2026  
**Status**: COMPLETE (331/331 tests passing)

---

## 1. Objective

The objective of Phase 6 is to apply formal **Decision Table Testing** to the Autonomous Revenue Recovery System. Decision Table Testing focuses on complex system behaviors determined by **combinations of boolean conditions** and explicitly validates **rule precedence**, **masking cascades**, and **deterministic action dispatch** across the multi-layered recovery pipeline.

---

## 2. Modules Analyzed

We analyzed the production implementation across five primary modules:
1. `src/guardrails.py`: Deterministic safety and compliance rule hierarchy.
2. `src/root_cause.py`: Tier 1 root cause diagnostics and error signal parsing.
3. `src/decision_engine.py`: Deterministic recovery playbook action selection.
4. `src/reconciliation.py`: Monotonic payment reconciliation state machine and timeout management.
5. `src/receivables.py`: B2B commercial invoice recovery, promise-to-pay tracking, and priority rules.

---

## 3. Decision Table Candidates

Four candidate subsystems were identified where multiple interacting inputs determine the system outcome:
1. **Guardrails Engine**: 9 conditions interacting through a strict 6-tier priority hierarchy.
2. **Root Cause & Playbook Dispatch**: 7 conditions mapping failure signals and execution indices to recovery playbooks.
3. **Payment Reconciliation**: 7 conditions determining state transitions, terminal invariant preservation, and timeout escalations.
4. **B2B Receivables Recovery**: 6 conditions determining commercial debt diagnosis, escalation pathways, and priority levels.

---

## 4. Guardrails Decision Table

The Guardrails decision table systematically proves rule precedence where higher-priority restrictions mask lower-priority violations:

| Condition / Rule | DT-G01 | DT-G02 | DT-G03 | DT-G04 | DT-G05 | DT-G06 | DT-G07 | DT-G08 | DT-G09 | DT-G10 | DT-G11 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Attempt $> 4$** | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **Mandate** | $-$ | **T** | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **T** | **F** |
| **Notice Served** | $-$ | **F** | **T** | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **F** | $-$ |
| **Retry Action** | $-$ | **T** | **T** | **T** | **F** | **F** | $-$ | **T** | **T** | **F** | **F** |
| **Cooldown Active** | $-$ | $-$ | **T** | **T** | $-$ | $-$ | **F** | **F** | **F** | $-$ | $-$ |
| **Customer-Facing** | $-$ | $-$ | $-$ | **F** | **T** | **T** | $-$ | **F** | **F** | **T** | **T** |
| **DND Active** | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **F** | **T** | **F** | **F** | **F** |
| **Opted Out** | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | $-$ | **T** | **F** | **F** |
| **Amount $> 50k$** | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **F** | **F** | **F** |
| **Expected Action** | **$A_1$** | **$A_2$** | **$A_3$** | **$A_3$** | **$A_4$** | **$A_5$** | **$A_6$** | **$A_7$** | **$A_7$** | **$A_7$** | **$A_7$** |

- **$A_1$**: `BLOCK: retry_cap_exceeded`
- **$A_2$**: `BLOCK: mandate_notice_required`
- **$A_3$**: `BLOCK: cooldown_active`
- **$A_4$**: `BLOCK: dnd_hours`
- **$A_5$**: `BLOCK: customer_opted_out`
- **$A_6$**: `BLOCK: amount_requires_human_approval`
- **$A_7$**: `ALLOW: PASS`

---

## 5. Root Cause & Decision Engine Table

This table maps failure indicators to discrete root causes and determines the next action sequence:

| Condition / Rule | DT-R01 | DT-R02 | DT-R03 | DT-R04 | DT-R05 | DT-R06 | DT-R07 | DT-R08 | DT-R09 | DT-R10 | DT-R11 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Chronic Flag** | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **Bank Timeout** | $-$ | **T** | **T** | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **NSF** | $-$ | $-$ | $-$ | $-$ | **T** | **T** | **F** | **F** | **F** | **F** | **F** |
| **Expired Card** | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **T** | **F** | **F** | **F** |
| **Cart Abandon** | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **F** |
| **Recent Overdue** | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** |
| **Action Index** | **0** | **0** | **1** | **2** | **0** | **1** | **0** | **1** | **0** | **0** | **0** |
| **Root Cause** | Chronic | Timeout | Timeout | Timeout | NSF | NSF | Expired | Expired | Cart | Overdue | Unknown |
| **Next Action** | `None` | Retry | Link | `None` | DelRetry | Link | Link | Remind | Nudge | Remind | `None` |

---

## 6. Reconciliation Table

This table validates the payment state machine and monotonic terminal invariants:

| Condition / Rule | DT-M01 | DT-M02 | DT-M03 | DT-M04 | DT-M05 | DT-M06 | DT-M07 | DT-M08 | DT-M09 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Current `RECOVERED`** | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **Status Captured** | $-$ | **T** | **F** | **F** | **F** | **F** | **F** | **F** | **F** |
| **Status Authorized** | $-$ | $-$ | **T** | **F** | **F** | **F** | **F** | **F** | **F** |
| **Status Failed** | $-$ | $-$ | $-$ | **T** | **T** | **F** | **F** | **F** | **F** |
| **Auto-Resume** | $-$ | $-$ | $-$ | **T** | **F** | $-$ | $-$ | $-$ | $-$ |
| **Attempts $\ge 3$** | $-$ | $-$ | $-$ | $-$ | $-$ | **T** | **F** | **T** | **F** |
| **Hours $\ge 24$** | $-$ | $-$ | $-$ | $-$ | $-$ | **F** | **T** | **T** | **F** |
| **Result Status** | Already | Reconciled | AuthPending | RecFailed | RecFailed | EscTimeout | EscTimeout | EscTimeout | Pending |
| **New DB Status** | `RECOVERED` | `RECOVERED` | `IN_PROGRESS` | `IN_PROGRESS` | `IN_PROGRESS` | `ESCALATED` | `ESCALATED` | `ESCALATED` | `IN_PROGRESS` |

---

## 7. B2B Receivables Table

This table verifies B2B commercial recovery paths, priority assignments, and immediate escalation rules:

| Condition / Rule | DT-B01 | DT-B02 | DT-B03 | DT-B04 | DT-B05 | DT-B06 | DT-B07 | DT-B08 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **B2B Enabled** | **F** | **T** | **T** | **T** | **T** | **T** | **T** | **T** |
| **P2P Missed** | $-$ | **T** | **T** | **F** | **F** | **F** | **F** | **F** |
| **Chronic Tier** | $-$ | **T** | $-$ | **T** | **F** | **F** | **F** | **F** |
| **Overdue $> 90$** | $-$ | **T** | $-$ | $-$ | **T** | **F** | **F** | **F** |
| **Amount $\ge 10k$** | $-$ | **T** | **F** | **T** | **F** | **F** | **T** | **F** |
| **Enterprise Tier** | $-$ | $-$ | **F** | $-$ | **F** | **T** | **F** | **F** |
| **Root Cause** | — | P2P Missed | P2P Missed | Chronic | Chronic | Overdue | Overdue | Overdue |
| **Priority** | — | HIGH | MEDIUM | HIGH | MEDIUM | HIGH | HIGH | MEDIUM |
| **Final Status** | PermError | RECOVERED | RECOVERED | ESCALATED | ESCALATED | RECOVERED | RECOVERED | RECOVERED |

---

## 8. Traceability

Every decision rule maps directly to an automated test case in `tests/ft3/test_decision_tables.py`:
- Guardrails Rules: `test_dt_guardrails_rules[DT-G01..DT-G11]` (11 tests)
- Root Cause / Playbook Rules: `test_dt_root_cause_playbook_rules[DT-R01..DT-R11]` (11 tests)
- Reconciliation Rules: `test_dt_reconciliation_rules[DT-M01..DT-M09]` (9 tests)
- B2B Receivables Rules: `test_dt_b2b_receivables_rules[DT-B01..DT-B08]` (8 tests)

Full details are documented in `docs/testing/DECISION_TABLE_TEST_MATRIX.md`.

---

## 9. Test Execution Results

```bash
# Execute Decision Table test suite
./.venv/bin/pytest tests/ft3/test_decision_tables.py -v
# Result: 39 passed in 0.12s

# Execute full suite across all phases
./.venv/bin/pytest -q
# Result: 331 passed in 3.46s
```

### Metrics Summary:
- **Total Tests**: 331 (Baseline: 175 | BVA: +39 | ECP: +35 | CEG: +43 | Decision Tables: +39)
- **Passed**: 331 / 331 (100% pass rate)
- **Failed**: 0
- **Skipped**: 0
- **Errors**: 0

---

## 10. Coverage Before vs After

| Metric | Phase 2 (Baseline) | Phase 3 (BVA) | Phase 4 (ECP) | Phase 5 (CEG) | Phase 6 (DT) | Total Delta |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Total Automated Tests** | 175 | 214 | 249 | 292 | **331** | **+156 (+89.1%)** |
| **Statement Coverage** | 85.0% | 85.0% | 85.33% | 85.75% | **85.75%** | +0.75% |
| **Branch Coverage** | 82.0% | 82.0% | 83.0% | 83.0% | **83.0%** | +1.0% |
| **Missed Statements** | 327 | 327 | 320 | 311 | **311** | **-16 statements** |
| **Partial Branches** | 90 | 90 | 88 | 84 | **84** | **-6 branches** |

---

## 11. Important Findings

1. **Preemption Rigidity**:
   - The decision table confirms that Guardrail Rule 1 (`retry_cap_exceeded`) strictly preempts all other conditions, even if a transaction is simultaneous with an unserved mandate notice, active cooldown, DND hours, customer opt-out, and an amount exceeding ₹50,000.
2. **Backend Action Immunity**:
   - `SMART_RETRY` is verified to be completely unaffected by DND windows (Rule DT-G08) and customer opt-out flags (Rule DT-G09), allowing automated nighttime retries to recover revenue silently.
3. **P2P Precedence over Chronic Flags**:
   - When a promise-to-pay date is missed in B2B receivables (Rule DT-B02), the system classifies the debt as `PROMISE_TO_PAY_MISSED` rather than `CHRONIC_NON_PAYER`, ensuring that an actionable reminder/link playbook is triggered before escalating to human collections.
4. **Closed-Loop Reconciliation Safety**:
   - The reconciliation state machine guarantees terminal monotonicity (Rule DT-M01), preventing late failure webhooks from corrupting verified financial recoveries.

---

## 12. Conclusion

Phase 6 (Decision Table Testing) is complete. The system now has **331 automated tests** running in ~3.5 seconds with **85.75% statement coverage and 83% branch coverage**. All 39 decision rules across the 4 key subsystems have 100% automated test coverage and full traceability.
