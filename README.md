# Autonomous AI Revenue Recovery System

**Track**: Razorpay Buildathon, Track 03  
**Status**: **Phases 1–14 100% Complete & Verified (`151/151 PASSED`)**

An autonomous, policy-governed revenue recovery platform designed to recover failed payments, checkout abandonments, and overdue B2B receivables. The system diagnoses failure root causes, evaluates deterministic compliance guardrails, executes recovery actions via mock or Razorpay sandbox endpoints, and drives closed-loop retries until recovery or human escalation.

---

## Key Highlights

- **Unified Control Plane**: Rules & deterministic state machines maintain authoritative control over financial execution, retry limits, and compliance guardrails.
- **Bounded LLM Integration**: LLM provides root-cause diagnosis for ambiguous errors and drafts personalized customer messages, but **never** overrides financial execution limits or retry sequences.
- **Multi-Domain Support**:
  - **Payment Failure Recovery**: Closed-loop retries, smart retry, payment links, and customer reminders.
  - **Razorpay Sandbox Integration**: Webhook HMAC-SHA256 signature verification, idempotency deduplication (`x-razorpay-event-id`), and payment status reconciliation.
  - **B2B Receivables Recovery**: Invoices, overdue tracking, promise-to-pay tracking, and CRM/collections escalation.
  - **Information Gathering**: Bounded single-question customer clarification for unknown root causes with 7-day recovery eligibility window.
  - **Hinglish Voice Recovery Interface**: Outbound call eligibility pre-checks, Hinglish intent classification, TwiML generation, and pluggable mock/real STT/TTS adapters.
- **Immutable Audit Trail**: Append-only log capturing every layer from ingestion to final status.
- **Live Interactive Dashboard**: FastAPI + React dashboard displaying real-time metrics, root cause distributions, action analytics, and transaction audit drill-downs.

---

## Quick Start

### 1. Prerequisites & Setup
```bash
# Clone repository
git clone https://github.com/rishabh-nagar-9100/Autonomous-Revenue-Recovery-System.git
cd Autonomous-Revenue-Recovery-System

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Automated Tests
```bash
# Run full test suite (151 tests)
pytest -v
```

### 3. Run Demo Rehearsal Batch
```bash
# Run 65-event synthetic demo rehearsal
python demo_rehearsal.py
```

### 4. Launch Local Web Application
```bash
# Start FastAPI Web Server & UI
uvicorn src.server:app --port 8000 --host 127.0.0.1
```
- **Dashboard UI**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive API Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Project Documentation

- [FINAL_PROJECT_HANDOFF.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/FINAL_PROJECT_HANDOFF.md) — Comprehensive technical handoff & system specs
- [PROJECT_CONTEXT.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/PROJECT_CONTEXT.md) — Core principles & architectural boundaries
- [ARCHITECTURE.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/ARCHITECTURE.md) — 8-layer pipeline, data model, and extensions
- [BUILD_PLAN.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/BUILD_PLAN.md) — Phase-by-phase implementation checklist
- [DECISIONS.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/DECISIONS.md) — Append-only architectural decision log
- [STATE.md](file:///Users/rishabhnagar9100/Desktop/Ai%20Revenue/STATE.md) — Current state, metrics, and QA guidelines

---

## License
MIT License
