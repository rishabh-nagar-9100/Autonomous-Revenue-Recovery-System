# Phase 5 — Cause-Effect Graph Testing Report

**Autonomous Revenue Recovery System — Software Testing FT3**  
**Technique**: Cause-Effect Graphing (Black-Box / Specification-Based Test Design)  
**Execution Date**: October 2026  
**Status**: COMPLETE (All 292 tests passing)

---

## 1. Executive Summary

Phase 5 applied Glenford Myers' formal **Cause-Effect Graph Testing** technique to the production codebase of the Autonomous Revenue Recovery System. Whereas previous phases evaluated individual input limits (BVA) and equivalence partitions (ECP) in isolation, Cause-Effect Graphing specifically targeted **multi-variable Boolean logic**, **combinational gates (AND, OR, NOT)**, and **priority masking cascades** where evaluation order dictates which rule fires and which are suppressed.

### Key Milestone Achievements
1. **Formal Graph Specification**: Authored `docs/testing/CAUSE_EFFECT_GRAPH.md` defining causes ($C_i$), intermediate logic gates ($I_j$), effects ($E_k$), and Mermaid flowcharts across 6 core subsystems.
2. **Automated Test Suite**: Implemented `tests/ft3/test_cause_effect_graph.py` adding **+43 new automated tests** systematically covering Boolean interaction paths and priority preemption.
3. **100% Suite Pass Rate**: Expanded test suite from 249 to **292 total automated tests** with **0 failures, 0 regressions**.
4. **Coverage Improvement**:
   - Total statements: 2,182 | Missed: 311 (reduced from 320 in ECP)
   - Branch coverage: 83% | Partial branches: 84 (reduced from 88 in ECP)
   - `src/risk_detector.py`: **100% Statement + 100% Branch Coverage**
   - `src/decision_engine.py`: **100% Statement + 100% Branch Coverage**
   - `src/root_cause.py`: **98% Coverage** (0 missed statements)
   - `src/guardrails.py`: **97% Coverage**
   - `src/receivables.py`: **93% Coverage** (increased from 88%)
   - `src/info_gathering.py`: **93% Coverage** (increased from 87%)
   - `src/voice.py`: **88% Coverage** (increased from 85%)

---

## 2. Subsystems Analyzed & Graph Metrics

| Subsystem | Source Module | Causes ($C$) | Intermediates ($I$) | Effects ($E$) | Tests Added |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Deterministic Guardrails** | `src/guardrails.py` | 10 | 6 | 7 | 11 |
| **Revenue Risk Detection** | `src/risk_detector.py` | 7 | 4 | 6 | 5 |
| **Root Cause Diagnostics** | `src/root_cause.py` | 11 | 6 | 7 | 6 |
| **Payment Reconciliation** | `src/reconciliation.py` | 7 | 5 | 6 | 7 |
| **B2B Receivables Engine** | `src/receivables.py` | 7 | 5 | 6 | 6 |
| **Auxiliary Communication** | `src/voice.py` / `src/info_gathering.py` | 10 | 4 | 8 | 8 |
| **TOTAL** | — | **52** | **30** | **40** | **43** |

---

## 3. Detailed Subsystem Analysis

### 3.1 Subsystem 1: Deterministic Guardrails (`src/guardrails.py`)
- **Causes**:
  - $C_1$: `attempt_number > 4` (`MAX_RETRY_ATTEMPTS`)
  - $C_2$: `is_mandate == True`
  - $C_3$: `mandate_notice_served == True`
  - $C_4$: `action_type in RETRY_ACTIONS`
  - $C_5$: `last_retry_at is not None`
  - $C_6$: `elapsed_seconds < 14400` (4h cooldown)
  - $C_7$: `action_type in CUSTOMER_FACING_ACTIONS`
  - $C_8$: `hour < 9 or hour >= 20` (DND window)
  - $C_9$: `customer_opted_out == True`
  - $C_{10}$: `amount > human_approval_threshold` (50,000.0)
- **Key Boolean Interactions**:
  - **Mandate Notice**: Requires $C_2 \wedge \neg C_3 \wedge C_4$ simultaneously. If notice is served ($\neg C_3$ is False) or action is non-retry ($C_4$ is False), the rule does not block.
  - **Cooldown**: Requires $C_5 \wedge C_6 \wedge C_4$. Non-retry actions (e.g. `PAYMENT_LINK`) pass through even if within 4 hours of a prior retry.
  - **DND Window**: Requires $C_7 \wedge C_8$. Backend retry actions (`SMART_RETRY`) are immune to DND restrictions and execute cleanly at night.
  - **Priority Masking**: Verified that Rule 1 (retry cap exceeded) preempts and masks all lower rules (Mandate, Cooldown, DND, Opt-out, Human Approval), and Rule 4 (DND) preempts Rule 5 (Opt-out).

### 3.2 Subsystem 2: Revenue Risk Detection (`src/risk_detector.py`)
- **Causes**: Amount thresholds ($\ge 10,000$, $\ge 2,500$), VIP flags (`is_vip` metadata or `customer_tier == "vip"`), Event types (`payment_failed`, `cart_abandonment`, `recent_overdue`, unrecognized).
- **Key Boolean Interactions**:
  - $I_{High} = C_{Amount \ge 10k} \vee C_{is\_vip} \vee C_{tier\_vip}$. A ₹100 transaction from a VIP is classified as `HIGH` priority, overriding the amount check.
  - $I_{Med} = \neg I_{High} \wedge C_{Amount \ge 2.5k}$. Evaluates only when not High.
  - Event type fallback: Unrecognized event types safely map to `RiskType.PAYMENT_FAILED`.

### 3.3 Subsystem 3: Root Cause Diagnostics (`src/root_cause.py`)
- **Causes**: Chronic indicators (consecutive failures $\ge 4$, `is_chronic_defaulter`, `chronic_non_payer` profile), Razorpay error codes/reasons (Bank Timeout, NSF, Expired Card, explicit chronic codes, unknown).
- **Key Boolean Interactions**:
  - $I_{ChronicMeta} = C_1 \vee C_2 \vee C_3$. Chronic metadata takes absolute priority over specific bank error codes (`GATEWAY_TIMEOUT`, `INSUFFICIENT_FUNDS`), immediately diagnosing `CHRONIC_NON_PAYER`.
  - Specific error code matching operates only when chronic flags are absent.

### 3.4 Subsystem 4: Payment Reconciliation (`src/reconciliation.py`)
- **Causes**: Current status (`RECOVERED` vs in-progress), Reconciled status (`SUCCESS`/`CAPTURED`, `AUTHORIZED`, `FAILED`, `PENDING`/`UNKNOWN`), Timeout thresholds (`attempt_count >= 3`, `elapsed_hours >= 24.0`), `auto_resume` flag.
- **Key Boolean Interactions**:
  - **Monotonic Terminal State Invariant**: $C_{current == RECOVERED}$ strictly blocks state regression. Attempting to reconcile a `FAILED` or `SUCCESS` status against an already recovered event returns `already_recovered` without modifying database state.
  - **Compound Timeout Gate**: $I_{Timeout} = C_{attempts \ge 3} \vee C_{hours \ge 24.0}$. If either threshold is crossed while status is unresolved, the system escalates to `ESCALATED`. If both are below threshold, status remains `pending_reconciliation`.
  - **Conditional Auto-Resume**: A reconciled `FAILED` status resumes the recovery workflow only if `auto_resume == True`.

### 3.5 Subsystem 5: B2B Receivables Recovery (`src/receivables.py`)
- **Causes**: `B2B_ENABLED` feature gate, Promise-to-pay date missed ($now > p2p\_date$), Days overdue $> 90$, Chronic customer tier, Amount due $\ge 10,000$, Enterprise tier.
- **Key Boolean Interactions**:
  - **P2P Priority**: Missed promise-to-pay ($C_{p2p} \wedge C_{now > p2p}$) overrides chronic non-payer classification, diagnosing `PROMISE_TO_PAY_MISSED`.
  - **Chronic Escalation**: If P2P is not missed, $C_{days > 90} \vee C_{tier == CHRONIC}$ triggers immediate human ops escalation (`status=ESCALATED`).
  - **Priority Assignment**: $C_{amount \ge 10k} \vee C_{tier == ENTERPRISE}$ assigns `HIGH` priority, ensuring Enterprise clients receive priority handling regardless of invoice amount.

### 3.6 Subsystem 6: Auxiliary Communication Engines (`src/voice.py` & `src/info_gathering.py`)
- **Causes**: Feature flags (`VOICE_ENABLED`, `INFO_GATHERING_ENABLED`), Communication guardrails (Opt-out, DND), Phone number validation ($digits \ge 10$), Terminal event status (`RECOVERED`, `ESCALATED`), Chronic non-payer classification, Attempt limits (single clarification request rule).
- **Key Boolean Interactions**:
  - Multi-gate voice pre-checks: Any single failure condition immediately halts the outbound call with a specific diagnostic reason.
  - Human-only case: Chronic non-payers are barred from autonomous voice recovery and routed exclusively to human ops.
  - Single clarification limit: Exactly one clarification request is permitted per risk event. Subsequent attempts are blocked and escalated.

---

## 4. Test Execution & Evolution Across Testing Phases

| Metric | Phase 2 (Baseline) | Phase 3 (BVA) | Phase 4 (ECP) | Phase 5 (CEG) | Total Delta |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Total Automated Tests** | **175** | **214** | **249** | **292** | **+117 (+66.9%)** |
| **Tests Passed** | 175 / 175 | 214 / 214 | 249 / 249 | 292 / 292 | 100% Pass |
| **New Tests Added** | — | +39 | +35 | **+43** | +117 |
| **Statement Coverage** | 85.0% | 85.0% | 85.33% | **85.75%** | +0.75% |
| **Branch Coverage** | 82.0% | 82.0% | 83.0% | **83.0%** | +1.0% |
| **Missed Statements** | 327 | 327 | 320 | **311** | **-16 statements** |
| **Partial Branches** | 90 | 90 | 88 | **84** | **-6 branches** |

---

## 5. Artifacts Created in Phase 5

1. `docs/testing/CAUSE_EFFECT_GRAPH.md`: Comprehensive specification detailing Causes, Intermediates, Effects, Boolean equations, Priority Cascades, and Mermaid diagrams for all 6 subsystems.
2. `tests/ft3/test_cause_effect_graph.py`: 43 automated pytest test cases validating combinational logic, priority masking, and state transitions.
3. `docs/testing/CAUSE_EFFECT_REPORT.md`: This comprehensive execution report documenting methodology, results, and metrics.

---

## 6. Conclusion & Next Phase Readiness

Phase 5 has successfully verified all compound Boolean logic, rule priority orders, and state transition invariants of the Autonomous Revenue Recovery System through formal Cause-Effect Graph Testing.

The test suite stands at **292 tests (292/292 passing)** with **85.75% statement coverage and 83% branch coverage**. The codebase is in a safe, verified, and pristine state, ready for **Phase 6 (Decision Tables)**.
