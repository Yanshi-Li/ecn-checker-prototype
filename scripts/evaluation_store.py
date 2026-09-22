"""Persistence primitives for identified ECN evaluation sessions."""


from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import psycopg
from psycopg.types.json import Jsonb
from hashlib import sha256
from datetime import datetime, timezone
import re


NOTIFICATION_STATUSES = frozenset({"requested", "sent", "failed"})
NOTIFICATION_KINDS = frozenset({"validation_report", "gate_notification", "other"})


def _safe_error_message(error: object) -> str | None:
    if error is None:
        return None
    message = str(error).strip()
    if not message:
        return None
    message = re.sub(r"(?i)(password|api[_ -]?key|token|secret)\s*[=:]\s*[^\s,;]+", r"\1=<REDACTED>", message)
    return message[:1000]


def _normalise_notification(kind: object, recipient: object, status: object) -> tuple[str, str, str]:
    notification_kind = str(kind or "").strip() or "other"
    if notification_kind not in NOTIFICATION_KINDS:
        notification_kind = "other"
    notification_recipient = str(recipient or "").strip()
    if not notification_recipient:
        raise ValueError("notification recipient must not be empty")
    notification_status = str(status or "").strip().lower()
    if notification_status not in NOTIFICATION_STATUSES:
        raise ValueError("notification status must be requested, sent, or failed")
    return notification_kind, notification_recipient, notification_status


def _insert_notification(connection, attempt_id: int, notification: Mapping[str, object]) -> None:
    kind, recipient, status = _normalise_notification(
        notification.get("kind") or notification.get("notification_kind"),
        notification.get("recipient"),
        notification.get("status"),
    )
    completed_at = notification.get("completed_at")
    if completed_at is None and status in {"sent", "failed"}:
        completed_at = datetime.now(timezone.utc)
    connection.execute(
        """INSERT INTO notification_attempts
           (precheck_attempt_id, notification_kind, recipient, status, requested_at, completed_at, error_message)
           VALUES (%s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s, %s)""",
        (attempt_id, kind, recipient, status, notification.get("requested_at"), completed_at,
         _safe_error_message(notification.get("error") or notification.get("error_message"))),
    )
    connection.execute(
        """INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
           SELECT session_id, id, %s, %s
           FROM precheck_attempts WHERE id = %s""",
        (f"notification_{status}", Jsonb({"kind": kind, "recipient": recipient}), attempt_id),
    )


_SCHEMA_PATH = Path(__file__).with_name("evaluation_schema.sql")


def persist_evaluation_snapshot(connection, session_id: int, snapshot: Mapping[str, object], files=()) -> int:
    """Persist a complete result, including ERROR cases, files, and notifications."""
    decision = str(snapshot.get("decision") or "").strip().upper() or None
    status = str(snapshot.get("status") or decision or "ERROR").strip().upper()
    if decision not in {None, "PASS", "FAIL"}:
        raise ValueError("snapshot decision must be PASS, FAIL, or empty for an error")
    if status not in {"PASS", "FAIL", "ERROR", "NOT_RUN"}:
        raise ValueError("snapshot status must be PASS, FAIL, ERROR, or NOT_RUN")

    payload = {key: value for key, value in snapshot.items() if key != "files"}
    event_type = "precheck_completed" if decision else "precheck_failed"
    event_metadata = {
        "system_decision": decision,
        "case_id": snapshot.get("case_id"),
        "status": status,
    }
    with connection.transaction():
        cursor = connection.execute(
            """INSERT INTO precheck_attempts
               (session_id, case_id, system_decision, started_at, completed_at, result_payload)
               VALUES (%s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), COALESCE(%s, CURRENT_TIMESTAMP), %s)
               RETURNING id""",
            (
                session_id,
                snapshot.get("precheck_case_id"),
                decision,
                snapshot.get("started_at"),
                snapshot.get("completed_at"),
                Jsonb(payload),
            ),
        )
        attempt_id = int(cursor.fetchone()[0])
        connection.execute(
            """INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
               VALUES (%s, %s, %s, %s)""",
            (session_id, attempt_id, event_type, Jsonb(event_metadata)),
        )
        store_evaluation_files(connection, attempt_id, files, _in_transaction=True)
        for notification in snapshot.get("notifications", ()) or ():
            _insert_notification(connection, attempt_id, notification)
    return attempt_id




save_evaluation_snapshot = persist_evaluation_snapshot


def store_evaluation_files(connection, attempt_id: int, files=(), _in_transaction: bool = False) -> None:
    """Attach original uploaded bytes to an existing pre-check attempt."""
    def insert_files() -> None:
        for file in files:
            raw = file.get("bytes", b"")
            if isinstance(raw, str):
                raw = raw.encode()
            if not isinstance(raw, (bytes, bytearray)):
                raise TypeError("file bytes must be bytes")
            raw = bytes(raw)
            role = str(file.get("role", "other"))
            if role not in {"ecn", "bom", "other"}:
                role = "other"
            connection.execute(
                """INSERT INTO evaluation_files
                   (precheck_attempt_id, role, filename, mime_type, size_bytes, sha256, captured_at, content)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (attempt_id, role, str(file.get("filename", "uploaded")),
                 str(file.get("mime_type", "application/octet-stream")), len(raw),
                 sha256(raw).hexdigest(), file.get("captured_at") or datetime.now(timezone.utc), raw),
            )

    if _in_transaction:
        insert_files()
    else:
        with connection.transaction():
            insert_files()



def record_notification_attempt(
    connection,
    attempt_id: int,
    notification_kind: str,
    recipient: str,
    status: str,
    error: object = None,
) -> None:
    """Record notification lifecycle state without storing credentials."""
    notification = {"kind": notification_kind, "recipient": recipient, "status": status, "error": error}
    with connection.transaction():
        _insert_notification(connection, attempt_id, notification)


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


def update_precheck_case_status(connection, case_id: int, status: str) -> None:
    """Store the latest status for one independent batch case."""
    normalized = status.strip().upper()
    if normalized not in {"PASS", "FAIL", "ERROR", "NOT_RUN"}:
        raise ValueError("status must be PASS, FAIL, ERROR, or NOT_RUN")

    with connection.transaction():
        cursor = connection.execute(
            """
            UPDATE precheck_cases
            SET status = %s
            WHERE id = %s
            RETURNING id
            """,
            (normalized, case_id),
        )
        if cursor.fetchone() is None:
            raise ValueError("pre-check case was not found")


def complete_evaluation_batch(connection, batch_id: int, status: str) -> None:
    """Mark a persisted batch as completed with its aggregate status."""
    normalized = status.strip().upper()
    if normalized not in {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "CANCELLED"}:
        raise ValueError("invalid evaluation batch status")

    with connection.transaction():
        cursor = connection.execute(
            """
            UPDATE evaluation_batches
            SET status = %s, completed_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
            """,
            (normalized, batch_id),
        )
        if cursor.fetchone() is None:
            raise ValueError("evaluation batch was not found")


def fail_precheck(
    connection, attempt_id: int, session_id: int, error_message: str
) -> None:
    """Record an execution error without inventing a PASS/FAIL decision."""
    message = _safe_error_message(error_message) or "Unknown pre-check error"

    with connection.transaction():

        cursor = connection.execute(
            """
            UPDATE precheck_attempts
            SET completed_at = CURRENT_TIMESTAMP,
                result_payload = %s
            WHERE id = %s AND session_id = %s
            RETURNING id
            """,
            (Jsonb({"error": message}), attempt_id, session_id),
        )
        if cursor.fetchone() is None:
            raise ValueError("pre-check attempt was not found for this session")
        connection.execute(
            """
            INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
            VALUES (%s, %s, 'precheck_failed', %s)
            """,
            (session_id, attempt_id, Jsonb({"error": message})),
        )


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
