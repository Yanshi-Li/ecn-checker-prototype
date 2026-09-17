"""Read and review persisted ECN pre-check attempts.

This module is the database seam for the lightweight reviewer dashboard.  It
returns plain dictionaries so the Streamlit rendering layer does not know SQL
or PostgreSQL details.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Mapping

from psycopg.types.json import Jsonb


DECISIONS = ("ALL", "PASS", "FAIL")
AGREEMENT_STATES = ("ALL", "AGREED", "DISAGREED", "UNJUDGED")


def _rows(cursor) -> list[dict[str, object]]:
    description = getattr(cursor, "description", None) or ()
    names = [column.name if hasattr(column, "name") else column[0] for column in description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _row(cursor) -> dict[str, object] | None:
    rows = _rows(cursor)
    return rows[0] if rows else None


def _where(filters: Mapping[str, object] | None = None, alias: str = "a"):
    filters = filters or {}
    clauses = [f"{alias}.system_decision IS NOT NULL"]
    params: list[object] = []
    decision = str(filters.get("system_decision", "ALL")).upper()
    if decision in {"PASS", "FAIL"}:
        clauses.append(f"{alias}.system_decision = %s")
        params.append(decision)
    case_identifier = str(filters.get("case_identifier", "")).strip()
    if case_identifier:
        clauses.append("le.logical_ecn_key ILIKE %s")
        params.append(f"%{case_identifier}%")
    tester = str(filters.get("tester", "")).strip()
    if tester:
        clauses.append("(s.tester_email ILIKE %s OR COALESCE(s.tester_name, '') ILIKE %s)")
        params.extend((f"%{tester}%", f"%{tester}%"))
    agreement = str(filters.get("agreement", "ALL")).upper()
    if agreement == "AGREED":
        clauses.append("j.judgement = a.system_decision")
    elif agreement == "DISAGREED":
        clauses.append("j.judgement IS NOT NULL AND j.judgement <> a.system_decision")
    elif agreement == "UNJUDGED":
        clauses.append("j.judgement IS NULL")
    start = filters.get("date_start")
    end = filters.get("date_end")
    if start:
        clauses.append(f"{alias}.started_at >= %s")
        params.append(datetime.combine(start, datetime.min.time()) if isinstance(start, date) else start)
    if end:
        clauses.append(f"{alias}.started_at < %s")
        params.append(datetime.combine(end, datetime.max.time()) if isinstance(end, date) else end)
    return " AND ".join(clauses), params


_BASE_FROM = """
FROM precheck_attempts a
JOIN evaluation_sessions s ON s.id = a.session_id
LEFT JOIN precheck_cases pc ON pc.id = a.case_id
LEFT JOIN logical_ecns le ON le.id = pc.logical_ecn_id
LEFT JOIN tester_judgements j ON j.precheck_attempt_id = a.id
"""


def list_attempts(connection, filters: Mapping[str, object] | None = None) -> list[dict[str, object]]:
    """List completed attempts, with optional reviewer filters."""
    where, params = _where(filters)
    cursor = connection.execute(
        """SELECT a.id AS attempt_id, a.system_decision, a.started_at, a.completed_at,
                  EXTRACT(EPOCH FROM (a.completed_at - a.started_at)) AS duration_seconds,
                  COALESCE(le.logical_ecn_key, a.result_payload->>'case_id') AS case_identifier,
                  s.tester_email, s.tester_name, j.judgement AS tester_judgement,
                  (j.judgement IS NOT NULL AND j.judgement = a.system_decision) AS agreement
           """ + _BASE_FROM + " WHERE " + where + " ORDER BY a.started_at DESC, a.id DESC",
        params,
    )
    return _rows(cursor)


def get_evaluation_summary(connection, filters: Mapping[str, object] | None = None) -> dict[str, object]:
    """Return counts and percentages for the same population as the attempt list."""
    attempts = list_attempts(connection, filters)
    total = len(attempts)
    passes = sum(row["system_decision"] == "PASS" for row in attempts)
    fails = sum(row["system_decision"] == "FAIL" for row in attempts)
    judged = [row for row in attempts if row.get("tester_judgement")]
    agreements = sum(row.get("agreement") is True for row in judged)
    percentage = lambda count, denominator: round((count / denominator) * 100, 1) if denominator else 0.0
    return {
        "total_attempts": total,
        "pass_count": passes,
        "pass_percentage": percentage(passes, total),
        "fail_count": fails,
        "fail_percentage": percentage(fails, total),
        "judged_count": len(judged),
        "agreement_count": agreements,
        "agreement_percentage": percentage(agreements, len(judged)),
    }


def get_attempt_detail(connection, attempt_id: int) -> dict[str, object] | None:
    """Return one attempt, its full result payload, findings, and file metadata."""
    cursor = connection.execute(
        """SELECT a.id AS attempt_id, a.session_id, a.case_id, a.system_decision,
                  a.started_at, a.completed_at,
                  EXTRACT(EPOCH FROM (a.completed_at - a.started_at)) AS duration_seconds,
                  a.result_payload, s.tester_email, s.tester_name, s.task_name,
                  j.judgement AS tester_judgement, j.explanation AS judgement_explanation,
                  j.recorded_at AS judgement_recorded_at
           """ + _BASE_FROM + " WHERE a.id = %s" , (attempt_id,))
    detail = _row(cursor)
    if detail is None:
        return None
    files = _rows(connection.execute(
        """SELECT id, role, filename, mime_type, size_bytes, sha256, captured_at
           FROM evaluation_files WHERE precheck_attempt_id = %s ORDER BY id""", (attempt_id,)))
    detail["files"] = files
    payload = detail.get("result_payload") or {}
    packet = payload.get("packet", {}) if isinstance(payload, dict) else {}
    gate = packet.get("gate", {}) if isinstance(packet, dict) else {}
    findings: list[dict[str, object]] = []
    for category in ("blockers", "part_issues", "conflict_alerts", "warnings"):
        for finding in gate.get(category, []) or []:
            if isinstance(finding, dict):
                findings.append({"category": category, **finding})
    ai_notes = gate.get("ai_notes", {}) if isinstance(gate, dict) else {}
    for finding in ai_notes.get("flags", []) or []:
        if isinstance(finding, dict):
            findings.append({"category": "ai_notes", **finding})
    detail["findings"] = findings
    detail["payload"] = payload
    return detail


def save_tester_judgement(
    connection, attempt_id: int, judgement: str, explanation: str = "", reviewer_identity: str = ""
) -> None:
    """Record a separate judgement and audit event; never update system_decision."""
    value = judgement.strip().upper()
    if value not in {"PASS", "FAIL"}:
        raise ValueError("judgement must be PASS or FAIL")
    with connection.transaction():
        connection.execute(
            """INSERT INTO tester_judgements (precheck_attempt_id, judgement, explanation)
               VALUES (%s, %s, %s)
               ON CONFLICT (precheck_attempt_id) DO UPDATE SET judgement = EXCLUDED.judgement,
                 explanation = EXCLUDED.explanation, recorded_at = CURRENT_TIMESTAMP""",
            (attempt_id, value, explanation.strip() or None),
        )
        connection.execute(
            """INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
               SELECT session_id, id, 'tester_judgement_recorded', %s
               FROM precheck_attempts WHERE id = %s""",
            (Jsonb({"judgement": value, "reviewer_identity": reviewer_identity.strip()}), attempt_id),
        )


def get_original_file(connection, attempt_id: int, role: str) -> dict[str, object] | None:
    """Fetch one original file's bytes and safe metadata for a download button."""
    if role not in {"ecn", "bom", "other"}:
        raise ValueError("role must be ecn, bom, or other")
    cursor = connection.execute(
        """SELECT filename, mime_type, size_bytes, sha256, captured_at, content
           FROM evaluation_files WHERE precheck_attempt_id = %s AND role = %s
           ORDER BY id LIMIT 1""", (attempt_id, role))
    return _row(cursor)
