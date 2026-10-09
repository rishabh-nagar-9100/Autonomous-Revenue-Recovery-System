# White Box Traceability Matrix

**Autonomous Revenue Recovery System — Software Testing FT3**  
**Document**: `docs/testing/WHITE_BOX_TRACEABILITY.md`  
**Purpose**: Complete traceability from internal control flow branches, decision conditions, and execution paths to automated test cases.

---

## 1. Traceability Table

| Function | Path / Branch ID | Condition / Decision Evaluated | Test ID | Covered? |
| :--- | :--- | :--- | :--- | :---: |
| `evaluate_guardrails` | **WB-G01** | `ctx.attempt_number > 4` (True) | `test_dt_guardrails_rules[DT-G01]`, `test_ceg_g01` | **YES** |
| `evaluate_guardrails` | **WB-G02** | `is_mandate AND NOT notice_served AND is_retry` (True) | `test_dt_guardrails_rules[DT-G02]`, `test_ceg_g02` | **YES** |
| `evaluate_guardrails` | **WB-G03** | `notice_served == True` (Mandate branch bypassed) | `test_dt_guardrails_rules[DT-G03]`, `test_ceg_g02` | **YES** |
| `evaluate_guardrails` | **WB-G04** | `action not in RETRY_ACTIONS` (Mandate branch bypassed) | `test_dt_guardrails_rules[DT-G10]`, `test_ceg_g02` | **YES** |
| `evaluate_guardrails` | **WB-G05** | `cooldown_active AND is_retry` (True, elapsed $< 4$h) | `test_dt_guardrails_rules[DT-G04]`, `test_ceg_g04` | **YES** |
| `evaluate_guardrails` | **WB-G06** | `cooldown elapsed >= 4h` (Cooldown branch bypassed) | `test_ceg_g05`, `test_cooldown_elapsed_allows_retry` | **YES** |
| `evaluate_guardrails` | **WB-G07** | `is_customer_facing AND is_dnd_hours` (True, 22:00) | `test_dt_guardrails_rules[DT-G05]`, `test_ceg_g06` | **YES** |
| `evaluate_guardrails` | **WB-G08** | `action not in CUSTOMER_FACING` during DND (Backend Retry) | `test_dt_guardrails_rules[DT-G08]`, `test_ceg_g07` | **YES** |
| `evaluate_guardrails` | **WB-G09** | `customer_opted_out AND is_customer_facing` (True) | `test_dt_guardrails_rules[DT-G06]`, `test_ceg_g08` | **YES** |
| `evaluate_guardrails` | **WB-G10** | `amount > human_approval_threshold` (True, ₹75,000) | `test_dt_guardrails_rules[DT-G07]`, `test_ceg_g10` | **YES** |
| `evaluate_guardrails` | **WB-G11** | All guardrails satisfied $\to$ `PASS` (Clean path) | `test_dt_guardrails_rules[DT-G11]`, `test_ceg_g11` | **YES** |
| `default_guardrail_time` | **WB-G12** | `now.hour >= 20 or now.hour < 9` (Night replacement to 14:00) | `test_wb_default_guardrail_time_night_hours` | **YES (New)** |
| `diagnose_root_cause_rules` | **WB-R01** | `is_chronic_defaulter == True` $\to$ `CHRONIC_NON_PAYER` | `test_ceg_c01`, `test_dt_root_cause_playbook_rules[DT-R01]` | **YES** |
| `diagnose_root_cause_rules` | **WB-R02** | `consecutive_failures >= 4` $\to$ `CHRONIC_NON_PAYER` | `test_ceg_c02`, `test_dt_root_cause_playbook_rules[DT-R01]` | **YES** |
| `diagnose_root_cause_rules` | **WB-R03** | `reason in BANK_TIMEOUT_REASONS` $\to$ `BANK_TIMEOUT` | `test_ceg_c03`, `test_case_a_known_error_code_does_not_call_llm` | **YES** |
| `diagnose_root_cause_rules` | **WB-R04** | `code in BANK_TIMEOUT_CODES` $\to$ `BANK_TIMEOUT` | `test_ceg_c03`, `test_dt_root_cause_playbook_rules[DT-R02]` | **YES** |
| `diagnose_root_cause_rules` | **WB-R05** | `reason in NSF_REASONS` or `code in NSF_CODES` $\to$ `NSF` | `test_ceg_c04`, `test_dt_root_cause_playbook_rules[DT-R05]` | **YES** |
| `diagnose_root_cause_rules` | **WB-R06** | `reason/code in EXPIRED_CARD` $\to$ `EXPIRED_CARD` | `test_ceg_c05`, `test_dt_root_cause_playbook_rules[DT-R07]` | **YES** |
| `diagnose_root_cause_rules` | **WB-R07** | `event_type == cart_abandonment` $\to$ `CART_ABANDONMENT` | `test_ceg_r05`, `test_dt_root_cause_playbook_rules[DT-R09]` | **YES** |
| `diagnose_root_cause_rules` | **WB-R08** | `event_type == recent_overdue` $\to$ `RECENT_OVERDUE` | `test_ceg_r05`, `test_dt_root_cause_playbook_rules[DT-R10]` | **YES** |
| `diagnose_root_cause_rules` | **WB-R09** | Unmapped reason/code $\to$ `UNKNOWN` (Confidence 0.0) | `test_ceg_c06`, `test_dt_root_cause_playbook_rules[DT-R11]` | **YES** |
| `diagnose_root_cause` | **WB-R10** | `use_llm_fallback == False` directly returns UNKNOWN `source="rule"` | `test_wb_diagnose_root_cause_llm_disabled_fallback` | **YES (New)** |
| `reconcile_payment_status` | **WB-M01** | `if not row:` (Missing risk event in database) | `test_wb_reconciliation_missing_risk_event` | **YES (New)** |
| `reconcile_payment_status` | **WB-M02** | `current_status == RECOVERED` $\to$ Terminal invariant lock | `test_ceg_m01`, `test_dt_reconciliation_rules[DT-M01]` | **YES** |
| `reconcile_payment_status` | **WB-M03** | Terminal lock with metadata enrichment (`razorpay_payment_id`, `webhook_event_id`) | `test_wb_reconciliation_terminal_with_metadata` | **YES (New)** |
| `reconcile_payment_status` | **WB-M04** | `reconciled_status in {"RECOVERED", "SUCCESS", "CAPTURED"}` | `test_ceg_m02`, `test_dt_reconciliation_rules[DT-M02]` | **YES** |
| `reconcile_payment_status` | **WB-M05** | Reconciled capture with prior execution action index | `test_wb_reconciliation_capture_with_prior_executions` | **YES (New)** |
| `reconcile_payment_status` | **WB-M06** | `reconciled_status in {"AUTHORIZED", "payment.authorized"}` | `test_ceg_m03`, `test_dt_reconciliation_rules[DT-M03]` | **YES** |
| `reconcile_payment_status` | **WB-M07** | `reconciled_status == "FAILED"` with `auto_resume=True` | `test_dt_reconciliation_rules[DT-M04]`, `test_outcome_tracker_scenarios` | **YES** |
| `reconcile_payment_status` | **WB-M08** | `reconciled_status == "FAILED"` with `auto_resume=False` | `test_ceg_m04`, `test_dt_reconciliation_rules[DT-M05]` | **YES** |
| `reconcile_payment_status` | **WB-M09** | `attempt_count >= 3` $\to$ `ESCALATED` (`escalated_timeout`) | `test_ceg_m05`, `test_dt_reconciliation_rules[DT-M06]` | **YES** |
| `reconcile_payment_status` | **WB-M10** | `elapsed_hours >= 24.0` $\to$ `ESCALATED` (`escalated_timeout`) | `test_ceg_m06`, `test_dt_reconciliation_rules[DT-M07]` | **YES** |
| `reconcile_payment_status` | **WB-M11** | Unresolved within limits $\to$ `pending_reconciliation` | `test_ceg_m07`, `test_dt_reconciliation_rules[DT-M09]` | **YES** |
| `extract_reference_id` | **WB-W01** | Non-dict payload $\to$ returns `None` | `test_wb_webhook_extract_ref_non_dict_payload` | **YES (New)** |
| `extract_reference_id` | **WB-W02** | Valid reference ID in `order.entity.receipt` | `test_wb_webhook_extract_ref_order_receipt` | **YES (New)** |
| `extract_reference_id` | **WB-W03** | Valid reference ID in `payment_link.entity.reference_id` | `test_wb_webhook_extract_ref_payment_link_entity_reference` | **YES (New)** |
| `extract_reference_id` | **WB-W04** | Valid reference ID in `payment_link.entity.notes` | `test_wb_webhook_extract_ref_payment_link_notes` | **YES (New)** |
| `extract_reference_id` | **WB-W05** | Flattened top-level notes dictionary | `test_wb_webhook_extract_ref_top_level_notes` | **YES (New)** |
| `extract_reference_id` | **WB-W06** | Flattened top-level key (`reference_id` / `risk_id`) | `test_wb_webhook_extract_ref_top_level_keys` | **YES (New)** |
| `extract_event_id` | **WB-W07** | Fallback to `payload["id"]`, `payment.entity.id`, or MD5 hash | `test_wb_webhook_extract_event_id_fallbacks` | **YES (New)** |
| `handle_outcome` | **WB-O01** | Missing risk event record raises `ValueError` | `test_wb_handle_outcome_missing_risk_event` | **YES (New)** |
| `handle_outcome` | **WB-O02** | Missing root cause diagnosis record raises `ValueError` | `test_wb_handle_outcome_missing_root_cause` | **YES (New)** |
| `handle_outcome` | **WB-O03** | `execution_status == SUCCESS` $\to$ `RECOVERED` (Hard-stop) | `test_outcome_tracker_scenarios` | **YES** |
| `handle_outcome` | **WB-O04** | `execution_status == FAILED` with no next action $\to$ Escalate | `test_scenario_2_bank_timeout_all_failed_playbook_exhausted` | **YES** |
| `handle_outcome` | **WB-O05** | Guardrail block on next action $\to$ Hard-stop and Escalate | `test_scenario_3_guardrail_block_stops_workflow_and_escalates` | **YES** |
| `start_recovery_workflow` | **WB-O06** | Missing risk event or root cause raises `ValueError` | `test_wb_start_recovery_workflow_validation` | **YES (New)** |
| `process_b2b_receivable` | **WB-B01** | `B2B_ENABLED=false` raises `PermissionError` | `test_dt_b2b_receivables_rules[DT-B01]`, `test_ceg_b01` | **YES** |
| `process_b2b_receivable` | **WB-B02** | Missed P2P date $\to$ `PROMISE_TO_PAY_MISSED` | `test_dt_b2b_receivables_rules[DT-B02]`, `test_ceg_b02` | **YES** |
| `process_b2b_receivable` | **WB-B03** | Chronic tier or overdue $> 90$ days $\to$ Immediate `ESCALATED` | `test_dt_b2b_receivables_rules[DT-B04]`, `test_ceg_b03` | **YES** |
| `process_b2b_receivable` | **WB-B04** | Standard overdue $\to$ Recovery workflow initiated | `test_dt_b2b_receivables_rules[DT-B08]`, `test_ceg_b05` | **YES** |
| `process_b2b_receivable` | **WB-B05** | Workflow escalates $\to$ Updates receivable status to `ESCALATED` | `test_wb_b2b_process_workflow_escalation` | **YES (New)** |
| `can_request_info` | **WB-I01** | `is_info_gathering_enabled() == False` returns `False` | `test_wb_info_gathering_disabled_flag` | **YES (New)** |
| `can_request_info` | **WB-I02** | Prior clarification request exists returns `False` | `test_ceg_i01` | **YES** |
| `check_voice_eligibility` | **WB-V01** | Non-existent risk event returns `risk_event_not_found` | `test_voice_non_existent_risk_event` | **YES** |
| `check_voice_eligibility` | **WB-V02** | Chronic non-payer returns `human_only_case:chronic_non_payer` | `test_ceg_v06`, `test_dt_b2b_receivables_rules[DT-B04]` | **YES** |
