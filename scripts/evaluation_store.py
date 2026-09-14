"""Persistence primitives for identified ECN evaluation sessions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import psycopg
from psycopg.types.json import Jsonb

_SCHEMA_PATH = Path(__file__).with_name("evaluation_schema.sql")


def connect_evaluation_db(environ: Mapping[str, str] | None = None):
    """Open the local evaluation database using environment configuration."""
    environment = environ if environ is not None else os.environ
    password = environment.get("ECN_DB_PASSWORD")
    if not password:
        raise RuntimeError("ECN_DB_PASSWORD must be configured")

    return psycopg.connect(
        host=environment.get("ECN_DB_HOST", "localhost"),
        port=int(environment.get("ECN_DB_PORT", "5432")),
        dbname=environment.get(
            "ECN_DB_NAME", "ecn_prechecker_evaluation"
        ),
        user=environment.get("ECN_DB_USER", "ecn_app"),
        password=password,
    )


def initialise_schema(connection) -> None:
    """Create the evaluation tables if they do not already exist."""
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    with connection.transaction():
        connection.execute(schema)


def create_session(
    connection,
    tester_email: str,
    tester_name: str = "",
    task_name: str = "ECN pre-check",
) -> int:
    """Create an evaluation session and return its database identifier."""
    email = tester_email.strip()
    if not email:
        raise ValueError("tester_email must not be empty")

    with connection.transaction():
        cursor = connection.execute(
            """
            INSERT INTO evaluation_sessions (tester_email, tester_name, task_name)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (email, tester_name.strip() or None, task_name),
        )
        row = cursor.fetchone()
    return int(row[0])


def start_precheck(connection, session_id: int) -> int:
    """Create a pre-check attempt and its start event."""
    with connection.transaction():
        cursor = connection.execute(
            """
            INSERT INTO precheck_attempts (session_id, started_at)
            VALUES (%s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (session_id,),
        )
        attempt_id = int(cursor.fetchone()[0])
        connection.execute(
            """
            INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type)
            VALUES (%s, %s, 'precheck_started')
            """,
            (session_id, attempt_id),
        )
    return attempt_id


def complete_precheck(
    connection,
    attempt_id: int,
    session_id: int,
    system_decision: str,
    result_payload: Mapping[str, object] | None = None,
) -> float:
    """Complete a pre-check, record its event, and return duration in seconds."""
    decision = system_decision.strip().upper()
    if decision not in {"PASS", "FAIL"}:
        raise ValueError("system_decision must be PASS or FAIL")

    with connection.transaction():
        cursor = connection.execute(
            """
            UPDATE precheck_attempts
            SET system_decision = %s,
                completed_at = CURRENT_TIMESTAMP,
                result_payload = %s
            WHERE id = %s AND session_id = %s
            RETURNING EXTRACT(EPOCH FROM (completed_at - started_at))
            """,
            (decision, Jsonb(dict(result_payload or {})), attempt_id, session_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("pre-check attempt was not found for this session")
        connection.execute(
            """
            INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
            VALUES (%s, %s, 'precheck_completed', %s)
            """,
            (session_id, attempt_id, Jsonb({"system_decision": decision})),
        )
    return float(row[0])
