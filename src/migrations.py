import sqlite3
from datetime import datetime
from typing import List, Tuple, Callable


def create_schema_migrations_table(conn: sqlite3.Connection) -> None:
    """Ensures schema_migrations table exists for version tracking."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
        """)


def migration_v1_add_webhook_events(conn: sqlite3.Connection) -> None:
    """Migration 1: Add webhook_events table with processing lifecycle."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            event_id TEXT PRIMARY KEY,
            received_at TEXT NOT NULL,
            raw_payload TEXT NOT NULL,
            processing_status TEXT NOT NULL DEFAULT 'RECEIVED',
            processed_at TEXT,
            error_reason TEXT
        );
    """)


def migration_v2_add_reconciliation_state(conn: sqlite3.Connection) -> None:
    """Migration 2: Ensure reconciliation state tracking structures."""
    pass


def migration_v3_add_receivables(conn: sqlite3.Connection) -> None:
    """Migration 3: Add receivables table for B2B Receivables Recovery."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS receivables (
            receivable_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            invoice_id TEXT NOT NULL,
            amount_due REAL NOT NULL,
            due_date TEXT NOT NULL,
            days_overdue INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            customer_tier TEXT DEFAULT 'STANDARD',
            last_contacted_at TEXT,
            promise_to_pay_date TEXT,
            created_at TEXT NOT NULL
        );
    """)


def migration_v4_add_info_requests(conn: sqlite3.Connection) -> None:
    """Migration 4: Add info_requests table for bounded customer clarification."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS info_requests (
            risk_id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            response TEXT,
            extracted_root_cause TEXT,
            status TEXT NOT NULL DEFAULT 'REQUESTED',
            requested_at TEXT NOT NULL,
            responded_at TEXT,
            eligibility_check_result TEXT
        );
    """)


def migration_v5_add_voice_interactions(conn: sqlite3.Connection) -> None:
    """Migration 5: Add voice_interactions table for Hinglish voice recovery."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS voice_interactions (
            interaction_id TEXT PRIMARY KEY,
            risk_id TEXT NOT NULL,
            call_sid TEXT,
            eligibility_status TEXT NOT NULL,
            transcript TEXT,
            intent TEXT,
            action_requested TEXT,
            guardrail_result TEXT,
            execution_result TEXT,
            escalation_reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (risk_id) REFERENCES risk_events(risk_id)
        );
    """)


# Migration registry: (version, name, function)
MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "add_webhook_events", migration_v1_add_webhook_events),
    (2, "add_reconciliation_state", migration_v2_add_reconciliation_state),
    (3, "add_receivables", migration_v3_add_receivables),
    (4, "add_info_requests", migration_v4_add_info_requests),
    (5, "add_voice_interactions", migration_v5_add_voice_interactions),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Applies unapplied database migrations sequentially in version order.
    """
    create_schema_migrations_table(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT version FROM schema_migrations;")
    applied_versions = {row[0] for row in cursor.fetchall()}

    for version, name, migration_func in MIGRATIONS:
        if version not in applied_versions:
            with conn:
                migration_func(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?);",
                    (version, name, datetime.utcnow().isoformat()),
                )
