import sqlite3
from typing import Optional, List, Dict, Any
from datetime import datetime
from src.models import (
    RiskEvent,
    RootCause,
    Intervention,
    GuardrailCheck,
    Execution,
    Outcome,
    Escalation,
    AuditLogEntry,
    RiskType,
    Priority,
    EventStatus,
    RootCauseEnum,
    ActionType,
    GuardrailResultEnum,
    ExecutionStatusEnum,
    OutcomeResultEnum,
    EscalationStatusEnum,
    Receivable,
    ReceivableStatusEnum,
    InfoRequest,
    InfoRequestStatusEnum,
    VoiceInteraction,
    VoiceIntent,
)


def get_db_connection(db_path: str = "recovery.db") -> sqlite3.Connection:
    """Creates a connection to the SQLite database with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initializes the database schema for Phases 1 through 6."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS risk_events (
                risk_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                risk_type TEXT NOT NULL,
                amount REAL NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS root_causes (
                risk_id TEXT PRIMARY KEY,
                root_cause TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS interventions (
                risk_id TEXT NOT NULL,
                action_index INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                draft_message TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (risk_id, action_index),
                FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guardrail_checks (
                risk_id TEXT NOT NULL,
                action_index INTEGER NOT NULL,
                result TEXT NOT NULL,
                reason TEXT,
                checked_at TEXT NOT NULL,
                PRIMARY KEY (risk_id, action_index),
                FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                risk_id TEXT NOT NULL,
                action_index INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                execution_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outcomes (
                risk_id TEXT NOT NULL,
                action_index INTEGER NOT NULL,
                result TEXT NOT NULL,
                amount_recovered REAL NOT NULL,
                resolved_at TEXT NOT NULL,
                PRIMARY KEY (risk_id, action_index),
                FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS escalations (
                risk_id TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                escalated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                risk_id TEXT NOT NULL,
                layer TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                decision TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
            );
        """)

    from src.migrations import run_migrations
    run_migrations(conn)


def insert_risk_event(conn: sqlite3.Connection, risk_event: RiskEvent) -> None:
    """Inserts a risk event into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO risk_events (risk_id, event_id, risk_type, amount, priority, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                risk_event.risk_id,
                risk_event.event_id,
                risk_event.risk_type.value,
                risk_event.amount,
                risk_event.priority.value,
                risk_event.status.value,
                risk_event.created_at.isoformat(),
            ),
        )


def update_risk_event_status(conn: sqlite3.Connection, risk_id: str, status: EventStatus) -> None:
    """Updates the status of a risk event."""
    with conn:
        conn.execute(
            "UPDATE risk_events SET status = ? WHERE risk_id = ?",
            (status.value, risk_id),
        )


def insert_root_cause(conn: sqlite3.Connection, root_cause: RootCause) -> None:
    """Inserts a root cause diagnosis into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO root_causes (risk_id, root_cause, confidence, source, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                root_cause.risk_id,
                root_cause.root_cause.value,
                root_cause.confidence,
                root_cause.source,
                root_cause.created_at.isoformat(),
            ),
        )


def insert_intervention(conn: sqlite3.Connection, intervention: Intervention) -> None:
    """Inserts an intervention plan row into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO interventions (risk_id, action_index, action_type, draft_message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                intervention.risk_id,
                intervention.action_index,
                intervention.action_type.value,
                intervention.draft_message,
                intervention.created_at.isoformat(),
            ),
        )


def insert_guardrail_check(conn: sqlite3.Connection, check: GuardrailCheck) -> None:
    """Inserts or updates a guardrail check record into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO guardrail_checks (risk_id, action_index, result, reason, checked_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(risk_id, action_index) DO UPDATE SET
                result = excluded.result,
                reason = excluded.reason,
                checked_at = excluded.checked_at;
            """,
            (
                check.risk_id,
                check.action_index,
                check.result.value,
                check.reason,
                check.checked_at.isoformat(),
            ),
        )


def insert_execution(conn: sqlite3.Connection, execution: Execution) -> None:
    """Inserts an execution record into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO executions (risk_id, action_index, action_type, execution_id, status, executed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                execution.risk_id,
                execution.action_index,
                execution.action_type.value,
                execution.execution_id,
                execution.status.value,
                execution.executed_at.isoformat(),
            ),
        )


def insert_outcome(conn: sqlite3.Connection, outcome: Outcome) -> None:
    """Inserts an outcome record into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO outcomes (risk_id, action_index, result, amount_recovered, resolved_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                outcome.risk_id,
                outcome.action_index,
                outcome.result.value,
                outcome.amount_recovered,
                outcome.resolved_at.isoformat(),
            ),
        )


def insert_escalation(conn: sqlite3.Connection, escalation: Escalation) -> None:
    """Inserts or replaces an escalation record in the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO escalations (risk_id, reason, escalated_at, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(risk_id) DO UPDATE SET
                reason = excluded.reason,
                escalated_at = excluded.escalated_at,
                status = excluded.status
            """,
            (
                escalation.risk_id,
                escalation.reason,
                escalation.escalated_at.isoformat(),
                escalation.status.value,
            ),
        )


def insert_audit_log(conn: sqlite3.Connection, entry: AuditLogEntry) -> int:
    """Inserts an append-only audit log entry into the database and returns its row ID."""
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_log (risk_id, layer, input_json, output_json, decision, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.risk_id,
                entry.layer,
                entry.input_json,
                entry.output_json,
                entry.decision,
                entry.timestamp.isoformat(),
            ),
        )
        return cursor.lastrowid


def get_risk_event(conn: sqlite3.Connection, risk_id: str) -> Optional[RiskEvent]:
    """Retrieves a risk event by risk_id."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM risk_events WHERE risk_id = ?", (risk_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return RiskEvent(
        risk_id=row["risk_id"],
        event_id=row["event_id"],
        risk_type=RiskType(row["risk_type"]),
        amount=row["amount"],
        priority=Priority(row["priority"]),
        status=EventStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def get_root_cause(conn: sqlite3.Connection, risk_id: str) -> Optional[RootCause]:
    """Retrieves a root cause by risk_id."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM root_causes WHERE risk_id = ?", (risk_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return RootCause(
        risk_id=row["risk_id"],
        root_cause=RootCauseEnum(row["root_cause"]),
        confidence=row["confidence"],
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def get_intervention(conn: sqlite3.Connection, risk_id: str, action_index: int) -> Optional[Intervention]:
    """Retrieves an intervention by risk_id and action_index."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM interventions WHERE risk_id = ? AND action_index = ?",
        (risk_id, action_index),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return Intervention(
        risk_id=row["risk_id"],
        action_index=row["action_index"],
        action_type=ActionType(row["action_type"]),
        draft_message=row["draft_message"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def get_interventions_for_risk(conn: sqlite3.Connection, risk_id: str) -> List[Intervention]:
    """Retrieves all interventions for a given risk_id ordered by action_index."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM interventions WHERE risk_id = ? ORDER BY action_index ASC",
        (risk_id,),
    )
    rows = cursor.fetchall()
    return [
        Intervention(
            risk_id=row["risk_id"],
            action_index=row["action_index"],
            action_type=ActionType(row["action_type"]),
            draft_message=row["draft_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        for row in rows
    ]


def get_guardrail_check(conn: sqlite3.Connection, risk_id: str, action_index: int) -> Optional[GuardrailCheck]:
    """Retrieves a guardrail check by risk_id and action_index."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM guardrail_checks WHERE risk_id = ? AND action_index = ?",
        (risk_id, action_index),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return GuardrailCheck(
        risk_id=row["risk_id"],
        action_index=row["action_index"],
        result=GuardrailResultEnum(row["result"]),
        reason=row["reason"],
        checked_at=datetime.fromisoformat(row["checked_at"]),
    )


def get_guardrail_checks_for_risk(conn: sqlite3.Connection, risk_id: str) -> List[GuardrailCheck]:
    """Retrieves all guardrail checks for a given risk_id ordered by action_index."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM guardrail_checks WHERE risk_id = ? ORDER BY action_index ASC",
        (risk_id,),
    )
    rows = cursor.fetchall()
    return [
        GuardrailCheck(
            risk_id=row["risk_id"],
            action_index=row["action_index"],
            result=GuardrailResultEnum(row["result"]),
            reason=row["reason"],
            checked_at=datetime.fromisoformat(row["checked_at"]),
        )
        for row in rows
    ]


def get_execution(conn: sqlite3.Connection, execution_id: str) -> Optional[Execution]:
    """Retrieves an execution by execution_id."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM executions WHERE execution_id = ?", (execution_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return Execution(
        risk_id=row["risk_id"],
        action_index=row["action_index"],
        action_type=ActionType(row["action_type"]),
        execution_id=row["execution_id"],
        status=ExecutionStatusEnum(row["status"]),
        executed_at=datetime.fromisoformat(row["executed_at"]),
    )


def get_executions_for_risk(conn: sqlite3.Connection, risk_id: str) -> List[Execution]:
    """Retrieves all executions for a given risk_id ordered by executed_at."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM executions WHERE risk_id = ? ORDER BY executed_at ASC",
        (risk_id,),
    )
    rows = cursor.fetchall()
    return [
        Execution(
            risk_id=row["risk_id"],
            action_index=row["action_index"],
            action_type=ActionType(row["action_type"]),
            execution_id=row["execution_id"],
            status=ExecutionStatusEnum(row["status"]),
            executed_at=datetime.fromisoformat(row["executed_at"]),
        )
        for row in rows
    ]


def get_outcomes_for_risk(conn: sqlite3.Connection, risk_id: str) -> List[Outcome]:
    """Retrieves all outcomes for a given risk_id ordered by action_index."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM outcomes WHERE risk_id = ? ORDER BY action_index ASC",
        (risk_id,),
    )
    rows = cursor.fetchall()
    return [
        Outcome(
            risk_id=row["risk_id"],
            action_index=row["action_index"],
            result=OutcomeResultEnum(row["result"]),
            amount_recovered=row["amount_recovered"],
            resolved_at=datetime.fromisoformat(row["resolved_at"]),
        )
        for row in rows
    ]


def get_escalation(conn: sqlite3.Connection, risk_id: str) -> Optional[Escalation]:
    """Retrieves an escalation record by risk_id."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM escalations WHERE risk_id = ?", (risk_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return Escalation(
        risk_id=row["risk_id"],
        reason=row["reason"],
        escalated_at=datetime.fromisoformat(row["escalated_at"]),
        status=EscalationStatusEnum(row["status"]),
    )


def get_audit_trail_for_risk(conn: sqlite3.Connection, risk_id: str) -> List[AuditLogEntry]:
    """Retrieves the complete append-only audit trail for a risk_id ordered by id ASC."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM audit_log WHERE risk_id = ? ORDER BY id ASC",
        (risk_id,),
    )
    rows = cursor.fetchall()
    return [
        AuditLogEntry(
            id=row["id"],
            risk_id=row["risk_id"],
            layer=row["layer"],
            input_json=row["input_json"],
            output_json=row["output_json"],
            decision=row["decision"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
        for row in rows
    ]


def insert_receivable(conn: sqlite3.Connection, receivable: Receivable) -> None:
    """Inserts or replaces a receivable record into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO receivables (
                receivable_id, customer_id, invoice_id, amount_due, due_date,
                days_overdue, status, customer_tier, last_contacted_at, promise_to_pay_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(receivable_id) DO UPDATE SET
                amount_due = excluded.amount_due,
                due_date = excluded.due_date,
                days_overdue = excluded.days_overdue,
                status = excluded.status,
                customer_tier = excluded.customer_tier,
                last_contacted_at = excluded.last_contacted_at,
                promise_to_pay_date = excluded.promise_to_pay_date;
            """,
            (
                receivable.receivable_id,
                receivable.customer_id,
                receivable.invoice_id,
                receivable.amount_due,
                receivable.due_date.isoformat(),
                receivable.days_overdue,
                receivable.status.value,
                receivable.customer_tier,
                receivable.last_contacted_at.isoformat() if receivable.last_contacted_at else None,
                receivable.promise_to_pay_date.isoformat() if receivable.promise_to_pay_date else None,
                receivable.created_at.isoformat(),
            ),
        )


def get_receivable(conn: sqlite3.Connection, receivable_id: str) -> Optional[Receivable]:
    """Retrieves a receivable by receivable_id."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM receivables WHERE receivable_id = ?", (receivable_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return Receivable(
        receivable_id=row["receivable_id"],
        customer_id=row["customer_id"],
        invoice_id=row["invoice_id"],
        amount_due=row["amount_due"],
        due_date=datetime.fromisoformat(row["due_date"]),
        days_overdue=row["days_overdue"],
        status=ReceivableStatusEnum(row["status"]),
        customer_tier=row["customer_tier"],
        last_contacted_at=datetime.fromisoformat(row["last_contacted_at"]) if row["last_contacted_at"] else None,
        promise_to_pay_date=datetime.fromisoformat(row["promise_to_pay_date"]) if row["promise_to_pay_date"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def update_receivable_status(conn: sqlite3.Connection, receivable_id: str, status: ReceivableStatusEnum) -> None:
    """Updates the status of a receivable."""
    with conn:
        conn.execute("UPDATE receivables SET status = ? WHERE receivable_id = ?", (status.value, receivable_id))


def list_receivables(conn: sqlite3.Connection) -> List[Receivable]:
    """Retrieves all receivables ordered by created_at DESC."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM receivables ORDER BY created_at DESC")
    rows = cursor.fetchall()
    return [
        Receivable(
            receivable_id=row["receivable_id"],
            customer_id=row["customer_id"],
            invoice_id=row["invoice_id"],
            amount_due=row["amount_due"],
            due_date=datetime.fromisoformat(row["due_date"]),
            days_overdue=row["days_overdue"],
            status=ReceivableStatusEnum(row["status"]),
            customer_tier=row["customer_tier"],
            last_contacted_at=datetime.fromisoformat(row["last_contacted_at"]) if row["last_contacted_at"] else None,
            promise_to_pay_date=datetime.fromisoformat(row["promise_to_pay_date"]) if row["promise_to_pay_date"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        for row in rows
    ]


def insert_info_request(conn: sqlite3.Connection, info_req: InfoRequest) -> None:
    """Inserts or replaces an info_request record into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO info_requests (
                risk_id, question, response, extracted_root_cause, status,
                requested_at, responded_at, eligibility_check_result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(risk_id) DO UPDATE SET
                question = excluded.question,
                response = excluded.response,
                extracted_root_cause = excluded.extracted_root_cause,
                status = excluded.status,
                requested_at = excluded.requested_at,
                responded_at = excluded.responded_at,
                eligibility_check_result = excluded.eligibility_check_result;
            """,
            (
                info_req.risk_id,
                info_req.question,
                info_req.response,
                info_req.extracted_root_cause,
                info_req.status.value if isinstance(info_req.status, InfoRequestStatusEnum) else str(info_req.status),
                info_req.requested_at.isoformat(),
                info_req.responded_at.isoformat() if info_req.responded_at else None,
                info_req.eligibility_check_result,
            ),
        )


def get_info_request(conn: sqlite3.Connection, risk_id: str) -> Optional[InfoRequest]:
    """Retrieves an info_request by risk_id."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM info_requests WHERE risk_id = ?", (risk_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return InfoRequest(
        risk_id=row["risk_id"],
        question=row["question"],
        response=row["response"],
        extracted_root_cause=row["extracted_root_cause"],
        status=InfoRequestStatusEnum(row["status"]),
        requested_at=datetime.fromisoformat(row["requested_at"]),
        responded_at=datetime.fromisoformat(row["responded_at"]) if row["responded_at"] else None,
        eligibility_check_result=row["eligibility_check_result"],
    )


def update_info_request(
    conn: sqlite3.Connection,
    risk_id: str,
    response: Optional[str] = None,
    extracted_root_cause: Optional[str] = None,
    status: Optional[InfoRequestStatusEnum] = None,
    responded_at: Optional[datetime] = None,
    eligibility_check_result: Optional[str] = None,
) -> None:
    """Updates fields on an existing info_request."""
    info_req = get_info_request(conn, risk_id)
    if not info_req:
        return

    if response is not None:
        info_req.response = response
    if extracted_root_cause is not None:
        info_req.extracted_root_cause = extracted_root_cause
    if status is not None:
        info_req.status = status
    if responded_at is not None:
        info_req.responded_at = responded_at
    if eligibility_check_result is not None:
        info_req.eligibility_check_result = eligibility_check_result

    insert_info_request(conn, info_req)


def update_root_cause(
    conn: sqlite3.Connection,
    risk_id: str,
    new_root_cause: RootCauseEnum,
    source: str = "customer_info_clarification",
) -> None:
    """Updates or replaces the root_cause entry for a risk_id."""
    with conn:
        conn.execute(
            """
            INSERT INTO root_causes (risk_id, root_cause, confidence, source, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(risk_id) DO UPDATE SET
                root_cause = excluded.root_cause,
                confidence = excluded.confidence,
                source = excluded.source,
                created_at = excluded.created_at;
            """,
            (
                risk_id,
                new_root_cause.value,
                1.0,
                source,
                datetime.utcnow().isoformat(),
            ),
        )


def insert_voice_interaction(conn: sqlite3.Connection, interaction: VoiceInteraction) -> None:
    """Inserts or replaces a voice_interaction record into the database."""
    with conn:
        conn.execute(
            """
            INSERT INTO voice_interactions (
                interaction_id, risk_id, call_sid, eligibility_status, transcript,
                intent, action_requested, guardrail_result, execution_result,
                escalation_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(interaction_id) DO UPDATE SET
                call_sid = excluded.call_sid,
                eligibility_status = excluded.eligibility_status,
                transcript = excluded.transcript,
                intent = excluded.intent,
                action_requested = excluded.action_requested,
                guardrail_result = excluded.guardrail_result,
                execution_result = excluded.execution_result,
                escalation_reason = excluded.escalation_reason,
                created_at = excluded.created_at;
            """,
            (
                interaction.interaction_id,
                interaction.risk_id,
                interaction.call_sid,
                interaction.eligibility_status,
                interaction.transcript,
                interaction.intent.value if isinstance(interaction.intent, VoiceIntent) else str(interaction.intent) if interaction.intent else None,
                interaction.action_requested.value if isinstance(interaction.action_requested, ActionType) else str(interaction.action_requested) if interaction.action_requested else None,
                interaction.guardrail_result,
                interaction.execution_result,
                interaction.escalation_reason,
                interaction.created_at.isoformat(),
            ),
        )


def get_voice_interaction(conn: sqlite3.Connection, interaction_id: str) -> Optional[VoiceInteraction]:
    """Retrieves a voice interaction by interaction_id."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM voice_interactions WHERE interaction_id = ?", (interaction_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return VoiceInteraction(
        interaction_id=row["interaction_id"],
        risk_id=row["risk_id"],
        call_sid=row["call_sid"],
        eligibility_status=row["eligibility_status"],
        transcript=row["transcript"],
        intent=VoiceIntent(row["intent"]) if row["intent"] else None,
        action_requested=ActionType(row["action_requested"]) if row["action_requested"] else None,
        guardrail_result=row["guardrail_result"],
        execution_result=row["execution_result"],
        escalation_reason=row["escalation_reason"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def list_voice_interactions_for_risk(conn: sqlite3.Connection, risk_id: str) -> List[VoiceInteraction]:
    """Retrieves all voice interactions for a risk_id ordered by created_at DESC."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM voice_interactions WHERE risk_id = ? ORDER BY created_at DESC", (risk_id,))
    rows = cursor.fetchall()
    return [
        VoiceInteraction(
            interaction_id=row["interaction_id"],
            risk_id=row["risk_id"],
            call_sid=row["call_sid"],
            eligibility_status=row["eligibility_status"],
            transcript=row["transcript"],
            intent=VoiceIntent(row["intent"]) if row["intent"] else None,
            action_requested=ActionType(row["action_requested"]) if row["action_requested"] else None,
            guardrail_result=row["guardrail_result"],
            execution_result=row["execution_result"],
            escalation_reason=row["escalation_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        for row in rows
    ]
