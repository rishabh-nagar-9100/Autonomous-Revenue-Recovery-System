# Boundary Value Analysis (BVA) Test Matrix

This matrix documents the systematic application of Boundary Value Analysis to all critical boundaries identified in the Autonomous Revenue Recovery System implementation.

---

## BVA Boundary Inventory & Test Specifications

### BVA-RD-01: Risk Detector — Amount Tier 1 Boundary (₹2,500.00)
- **Module**: [`src/risk_detector.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/risk_detector.py#L15)
- **Variable**: `event.amount`
- **Comparison in Code**: `elif event.amount >= 2500.0:`
- **Preconditions**: `is_vip=False`, `customer_tier != "vip"`
- **Boundary Value**: `2500.00`
- **Specification**:
  - **Below Boundary (`2499.99`)**: `Priority.LOW`
  - **At Boundary (`2500.00`)**: `Priority.MEDIUM`
  - **Above Boundary (`2500.01`)**: `Priority.MEDIUM`
- **Existing Coverage Status**: Missing. Existing tests only checked arbitrary amounts (`₹800.0` and `₹4500.0`).

---

### BVA-RD-02: Risk Detector — Amount Tier 2 Boundary (₹10,000.00)
- **Module**: [`src/risk_detector.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/risk_detector.py#L13)
- **Variable**: `event.amount`
- **Comparison in Code**: `if event.amount >= 10000.0 or is_vip:`
- **Preconditions**: `is_vip=False`, `customer_tier != "vip"`
- **Boundary Value**: `10000.00`
- **Specification**:
  - **Below Boundary (`9999.99`)**: `Priority.MEDIUM`
  - **At Boundary (`10000.00`)**: `Priority.HIGH`
  - **Above Boundary (`10000.01`)**: `Priority.HIGH`
- **Existing Coverage Status**: Missing. Existing tests only checked `₹12,000.0` and `₹4,500.0`.

---

### BVA-GR-01: Guardrails — Maximum Retry Attempts Cap (4 Attempts)
- **Module**: [`src/guardrails.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/guardrails.py#L30-L82)
- **Variable**: `ctx.attempt_number` (constant `MAX_RETRY_ATTEMPTS = 4`)
- **Comparison in Code**: `if ctx.attempt_number > MAX_RETRY_ATTEMPTS:`
- **Preconditions**: All other guardrails passing
- **Boundary Value**: `4`
- **Specification**:
  - **Below Boundary (`3`)**: `GuardrailResultEnum.PASS`, reason `None`
  - **At Boundary (`4`)**: `GuardrailResultEnum.PASS`, reason `None`
  - **Above Boundary (`5`)**: `GuardrailResultEnum.BLOCK`, reason `"retry_cap_exceeded"`
- **Existing Coverage Status**: Partially covered in `test_phase3.py` (`attempt_number=4` passes, `attempt_number=5` blocks).

---

### BVA-GR-02: Guardrails — Cooldown Duration (14,400 Seconds / 4 Hours)
- **Module**: [`src/guardrails.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/guardrails.py#L33-L104)
- **Variable**: `elapsed = (ctx.current_time - ctx.last_retry_at).total_seconds()` (constant `COOLDOWN_SECONDS = 14400`)
- **Comparison in Code**: `if elapsed < COOLDOWN_SECONDS:`
- **Preconditions**: `action_type in RETRY_ACTIONS` (`SMART_RETRY` or `DELAYED_RETRY`)
- **Boundary Value**: `14400` seconds
- **Specification**:
  - **Below Boundary (`14399` s)**: `GuardrailResultEnum.BLOCK`, reason `"cooldown_active"`
  - **At Boundary (`14400` s)**: `GuardrailResultEnum.PASS`, reason `None`
  - **Above Boundary (`14401` s)**: `GuardrailResultEnum.PASS`, reason `None`
- **Existing Coverage Status**: Missing. Existing tests only checked 2 hours (7200s) and 5 hours (18000s).

---

### BVA-GR-03A: Guardrails — Do-Not-Disturb (DND) Morning Boundary (09:00 AM)
- **Module**: [`src/guardrails.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/guardrails.py#L26-L117)
- **Variable**: `current_hour = ctx.current_time.hour` (constant `DND_START_HOUR = 9`)
- **Comparison in Code**: `if current_hour < DND_START_HOUR or current_hour >= DND_END_HOUR:`
- **Preconditions**: `action_type in CUSTOMER_FACING_ACTIONS` (`PAYMENT_LINK`, `REMINDER`, `DISCOUNT_NUDGE`)
- **Boundary Value**: `09:00:00` (`hour = 9`)
- **Specification**:
  - **Below Boundary (`08:59:59` / hour=8)**: `GuardrailResultEnum.BLOCK`, reason `"dnd_hours"`
  - **At Boundary (`09:00:00` / hour=9)**: `GuardrailResultEnum.PASS`, reason `None`
  - **Above Boundary (`09:01:00` / hour=9)**: `GuardrailResultEnum.PASS`, reason `None`
- **Existing Coverage Status**: Missing exact minute boundaries. Existing tests checked `07:00` (7 AM) and `14:30` (2:30 PM).

---

### BVA-GR-03B: Guardrails — Do-Not-Disturb (DND) Evening Boundary (08:00 PM / 20:00)
- **Module**: [`src/guardrails.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/guardrails.py#L27-L117)
- **Variable**: `current_hour = ctx.current_time.hour` (constant `DND_END_HOUR = 20`)
- **Comparison in Code**: `if current_hour < DND_START_HOUR or current_hour >= DND_END_HOUR:`
- **Preconditions**: `action_type in CUSTOMER_FACING_ACTIONS`
- **Boundary Value**: `20:00:00` (`hour = 20`)
- **Specification**:
  - **Below Boundary (`19:59:59` / hour=19)**: `GuardrailResultEnum.PASS`, reason `None`
  - **At Boundary (`20:00:00` / hour=20)**: `GuardrailResultEnum.BLOCK`, reason `"dnd_hours"`
  - **Above Boundary (`20:01:00` / hour=20)**: `GuardrailResultEnum.BLOCK`, reason `"dnd_hours"`
- **Existing Coverage Status**: Missing exact minute boundaries. Existing tests checked `22:30` (10:30 PM) and `14:30` (2:30 PM).

---

### BVA-GR-04: Guardrails — Human Approval Amount Threshold (₹50,000.00)
- **Module**: [`src/guardrails.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/guardrails.py#L36-L137)
- **Variable**: `amount` (constant `DEFAULT_HUMAN_APPROVAL_AMOUNT_THRESHOLD = 50000.0`)
- **Comparison in Code**: `if amount > ctx.human_approval_threshold:`
- **Preconditions**: Higher priority guardrails pass
- **Boundary Value**: `50000.00`
- **Specification**:
  - **Below Boundary (`49999.99`)**: `GuardrailResultEnum.PASS`, reason `None`
  - **At Boundary (`50000.00`)**: `GuardrailResultEnum.PASS`, reason `None`
  - **Above Boundary (`50000.01`)**: `GuardrailResultEnum.BLOCK`, reason `"amount_requires_human_approval"`
- **Existing Coverage Status**: Missing. Existing tests checked `₹49,999.0` and `₹75,000.0`.

---

### BVA-RC-01: Reconciliation — Maximum Reconciliation Attempt Cap (3 Attempts)
- **Module**: [`src/reconciliation.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/reconciliation.py#L258)
- **Variable**: `attempt_count` (constant `MAX_RECONCILIATION_ATTEMPTS = 3`)
- **Comparison in Code**: `if attempt_count >= MAX_RECONCILIATION_ATTEMPTS or elapsed_hours >= MAX_RECONCILIATION_HOURS:`
- **Preconditions**: `elapsed_hours < 24.0`, unconfirmed status (not forced SUCCESS/RECOVERED)
- **Boundary Value**: `3`
- **Specification**:
  - **Below Boundary (`2`)**: `status: "pending_reconciliation"`
  - **At Boundary (`3`)**: `status: "escalated_timeout"`, new status `ESCALATED`
  - **Above Boundary (`4`)**: `status: "escalated_timeout"`, new status `ESCALATED`
- **Existing Coverage Status**: Missing. Completely untested in existing test suite.

---

### BVA-RC-02: Reconciliation — Maximum Reconciliation Elapsed Time (24.0 Hours)
- **Module**: [`src/reconciliation.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/reconciliation.py#L258)
- **Variable**: `elapsed_hours` (constant `MAX_RECONCILIATION_HOURS = 24.0`)
- **Comparison in Code**: `if attempt_count >= MAX_RECONCILIATION_ATTEMPTS or elapsed_hours >= MAX_RECONCILIATION_HOURS:`
- **Preconditions**: `attempt_count < 3`, unconfirmed status
- **Boundary Value**: `24.00` hours
- **Specification**:
  - **Below Boundary (`23.99` h)**: `status: "pending_reconciliation"`
  - **At Boundary (`24.00` h)**: `status: "escalated_timeout"`, new status `ESCALATED`
  - **Above Boundary (`24.01` h)**: `status: "escalated_timeout"`, new status `ESCALATED`
- **Existing Coverage Status**: Missing. Completely untested in existing test suite.

---

### BVA-B2B-01: B2B Receivables — Days Overdue Chronic Default Threshold (90 Days)
- **Module**: [`src/receivables.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/receivables.py#L40)
- **Variable**: `receivable.days_overdue`
- **Comparison in Code**: `if receivable.customer_tier == "CHRONIC_NON_PAYER" or receivable.days_overdue > 90:`
- **Preconditions**: `customer_tier = "STANDARD"`, `promise_to_pay_date = None`
- **Boundary Value**: `90` days
- **Specification**:
  - **Below Boundary (`89` days)**: `RootCauseEnum.RECEIVABLE_OVERDUE`
  - **At Boundary (`90` days)**: `RootCauseEnum.RECEIVABLE_OVERDUE` (strict `> 90`)
  - **Above Boundary (`91` days)**: `RootCauseEnum.CHRONIC_NON_PAYER`
- **Existing Coverage Status**: Missing exact boundary. Existing tests checked `15` days and `95` days.

---

### BVA-INFO-01: Customer Info Gathering — Recovery Window Expiration (7.0 Days)
- **Module**: [`src/info_gathering.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/info_gathering.py#L184-L185)
- **Variable**: `elapsed_days = (ref_time - risk_event.created_at).total_seconds() / 86400.0` (constant `INFO_RECOVERY_WINDOW_DAYS = 7`)
- **Comparison in Code**: `if elapsed_days > INFO_RECOVERY_WINDOW_DAYS:`
- **Preconditions**: `status = IN_PROGRESS`, `amount > 0`
- **Boundary Value**: `7.00` days
- **Specification**:
  - **Below Boundary (`6.99` days)**: `eligible: True`, reason `"PASS"`
  - **At Boundary (`7.00` days)**: `eligible: True`, reason `"PASS"` (strict `> 7`)
  - **Above Boundary (`7.01` days)**: `eligible: False`, reason contains `"recovery_window_expired"`
- **Existing Coverage Status**: Missing. Existing tests only checked active workflow without boundary timing.

---

### BVA-INFO-02: Customer Info Gathering — Minimum Transaction Amount (₹0.00)
- **Module**: [`src/info_gathering.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/info_gathering.py#L180-L181)
- **Variable**: `risk_event.amount`
- **Comparison in Code**: `if risk_event.amount <= 0:`
- **Preconditions**: `status = IN_PROGRESS`, `elapsed_days <= 7`
- **Boundary Value**: `0.00`
- **Specification**:
  - **Below Boundary (`-0.01`)**: `eligible: False`, reason `"invalid_amount"`
  - **At Boundary (`0.00`)**: `eligible: False`, reason `"invalid_amount"`
  - **Above Boundary (`0.01`)**: `eligible: True`, reason `"PASS"`
- **Existing Coverage Status**: Missing. Never tested zero or negative amounts.

---

### BVA-VOICE-01: Voice Recovery — Phone Number Digit Count (10 Digits)
- **Module**: [`src/voice.py`](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/src/voice.py#L99-L101)
- **Variable**: `len(clean_phone)` where `clean_phone = "".join(c for c in phone_number if c.isdigit())`
- **Comparison in Code**: `if len(clean_phone) < 10:`
- **Preconditions**: `VOICE_ENABLED = True`, not opted out, daytime hours
- **Boundary Value**: `10` digits
- **Specification**:
  - **Below Boundary (`9` digits)**: `eligible: False`, reason `"invalid_phone_number"`
  - **At Boundary (`10` digits)**: `eligible: True`
  - **Above Boundary (`11` digits)**: `eligible: True`
- **Existing Coverage Status**: Missing. Existing test only checked 3 digits (`"123"`).

---

## Summary Matrix

| ID | Module | Variable | Comparison | Below Boundary | Boundary Value | Above Boundary | Expected (Below / At / Above) |
|---|---|---|:---:|:---:|:---:|:---:|---|
| **BVA-RD-01** | `risk_detector` | `amount` | `>= 2500.0` | `2499.99` | `2500.00` | `2500.01` | LOW / MEDIUM / MEDIUM |
| **BVA-RD-02** | `risk_detector` | `amount` | `>= 10000.0` | `9999.99` | `10000.00` | `10000.01` | MEDIUM / HIGH / HIGH |
| **BVA-GR-01** | `guardrails` | `attempt_number` | `> 4` | `3` | `4` | `5` | PASS / PASS / BLOCK |
| **BVA-GR-02** | `guardrails` | `elapsed_seconds` | `< 14400` | `14399` | `14400` | `14401` | BLOCK / PASS / PASS |
| **BVA-GR-03A**| `guardrails` | `current_time` (Morning) | `< 9` (hour) | `08:59:59` | `09:00:00` | `09:01:00` | BLOCK / PASS / PASS |
| **BVA-GR-03B**| `guardrails` | `current_time` (Evening) | `>= 20` (hour) | `19:59:59` | `20:00:00` | `20:01:00` | PASS / BLOCK / BLOCK |
| **BVA-GR-04** | `guardrails` | `amount` | `> 50000.0` | `49999.99` | `50000.00` | `50000.01` | PASS / PASS / BLOCK |
| **BVA-RC-01** | `reconciliation`| `attempt_count` | `>= 3` | `2` | `3` | `4` | PENDING / TIMEOUT / TIMEOUT |
| **BVA-RC-02** | `reconciliation`| `elapsed_hours` | `>= 24.0` | `23.99` | `24.00` | `24.01` | PENDING / TIMEOUT / TIMEOUT |
| **BVA-B2B-01** | `receivables` | `days_overdue` | `> 90` | `89` | `90` | `91` | OVERDUE / OVERDUE / CHRONIC |
| **BVA-INFO-01**| `info_gathering`| `elapsed_days` | `> 7.0` | `6.99` | `7.00` | `7.01` | ELIGIBLE / ELIGIBLE / EXPIRED |
| **BVA-INFO-02**| `info_gathering`| `amount` | `<= 0.0` | `-0.01` | `0.00` | `0.01` | INVALID / INVALID / ELIGIBLE |
| **BVA-VOICE-01**| `voice` | `phone_digits` | `< 10` | `9 digits` | `10 digits` | `11 digits` | INVALID / ELIGIBLE / ELIGIBLE |
