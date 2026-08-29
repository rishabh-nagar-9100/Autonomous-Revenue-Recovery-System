# SESSION KICKOFF — paste this exact prompt to start every session

---

Read PROJECT_CONTEXT.md, STATE.md, DECISIONS.md, ARCHITECTURE.md, BUILD_PLAN.md, POST_MVP_EXPANSION_PLAN.md, and latest walkthrough/handoff documents in full before doing anything else.

Determine current project status: **`FINAL QA / DEMO PREPARATION`** (All engineering phases 1–14 are 100% complete and verified; 151/151 tests pass).

Rules for this session:
1. **DO NOT immediately write implementation code or add new features.**
2. **Feature development is FROZEN.** Do not start Phase 15 without explicit project-lead instructions.
3. Preserve the core architecture principle: **LLM $\neq$ Financial Control Plane**.
4. The existing 151-test suite must remain green after any change (`pytest -v`).
5. In your VERY FIRST response:
   - State what is complete (Phases 1–14 complete, 151 tests passing).
   - State what is externally pending (Real Razorpay test mode smoke test, Real Twilio/STT/TTS voice smoke test).
   - Report current test count (`151/151 PASSED`).
   - Report current synthetic demo metrics (65 events, ₹6.50L at risk, ₹3.91L recovered, 60.26% rate, 8 blocks, 17 escalations).
   - Report current manual QA status.
   - Propose the specific manual QA / demo task you plan to perform.
6. Wait for project-lead approval before proceeding.

Now tell me back: current status, test count, demo metrics, pending external smoke tests, and what task you propose to work on. Wait for confirmation.

---

## Phase Reference Summary

| Phase Range | Scope | Status | Test Count |
| :--- | :--- | :---: | :---: |
| **Phases 1–9** | Core MVP (Payment Recovery Pipeline) | ✅ Complete | 92 tests |
| **Phase 10** | Razorpay Sandbox + Webhook Hardening | ✅ Complete | 15 tests |
| **Phase 11** | Network Jitter, Fault Injection & Invariants | ✅ Complete | 8 tests |
| **Phase 12** | B2B Receivables Recovery | ✅ Complete | 8 tests |
| **Phase 13** | Information Gathering for Unknown Root Cause | ✅ Complete | 12 tests |
| **Phase 14** | Hinglish Voice Recovery Interface | ✅ Complete | 16 tests |
| **Total Automated Tests** | **All 14 Engineering Phases** | **151/151 PASSED** | **151 tests** |
