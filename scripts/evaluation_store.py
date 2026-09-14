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


def create_evaluation_batch(
    connection,
    session_id: int,
    metadata: Mapping[str, object] | None = None,
) -> int:
    """Create a batch belonging to an identified evaluation session."""
    with connection.transaction():
        cursor = connection.execute(
            """
            INSERT INTO evaluation_batches (session_id, metadata)
            VALUES (%s, %s)
            RETURNING id
            """,
            (session_id, Jsonb(dict(metadata or {}))),
        )
        return int(cursor.fetchone()[0])


def create_logical_ecn(
    connection,
    batch_id: int,
    logical_ecn_key: str,
    metadata: Mapping[str, object] | None = None,
) -> int:
    """Add one normalized logical ECN to a batch."""
    key = logical_ecn_key.strip()
    if not key:
        raise ValueError("logical_ecn_key must not be empty")

    with connection.transaction():
        cursor = connection.execute(
            """
            INSERT INTO logical_ecns (batch_id, logical_ecn_key, metadata)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (batch_id, key, Jsonb(dict(metadata or {}))),
        )
        return int(cursor.fetchone()[0])


def create_bom_input(
    connection,
    batch_id: int,
    bom_key: str,
    bom_state: str,
    metadata: Mapping[str, object] | None = None,
) -> int:
    """Add an unassigned BOM input to a batch."""
    key = bom_key.strip()
    state = bom_state.strip().upper()
    if not key:
        raise ValueError("bom_key must not be empty")
    if state not in {"ABSENT", "EMPTY", "PRESENT"}:
        raise ValueError("bom_state must be ABSENT, EMPTY, or PRESENT")

    with connection.transaction():
        cursor = connection.execute(
            """
            INSERT INTO bom_inputs (batch_id, bom_key, bom_state, metadata)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (batch_id, key, state, Jsonb(dict(metadata or {}))),
        )
        return int(cursor.fetchone()[0])


def assign_bom_input(connection, bom_input_id: int, logical_ecn_id: int) -> None:
    """Assign a BOM input to exactly one logical ECN."""
    with connection.transaction():
        cursor = connection.execute(
            """
            UPDATE bom_inputs
            SET assigned_logical_ecn_id = %s
            WHERE id = %s AND assigned_logical_ecn_id IS NULL
            RETURNING id
            """,
            (logical_ecn_id, bom_input_id),
        )
        if cursor.fetchone() is None:
            raise ValueError("BOM input is missing or already assigned")


def create_precheck_case(
    connection,
    batch_id: int,
    logical_ecn_id: int,
    bom_input_id: int | None = None,
) -> int:
    """Create one independent ECN-only or ECN/BOM comparison case."""
    with connection.transaction():
        cursor = connection.execute(
            """
            INSERT INTO precheck_cases (batch_id, logical_ecn_id, bom_input_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (batch_id, logical_ecn_id, bom_input_id),
        )
        return int(cursor.fetchone()[0])


def start_precheck(connection, session_id: int, case_id: int | None = None) -> int:
    """Create a pre-check attempt and its start event."""
    with connection.transaction():
        cursor = connection.execute(
            """
            INSERT INTO precheck_attempts (session_id, case_id, started_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (session_id, case_id),
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
