"""Read and review persisted ECN pre-check attempts.

This module is the database seam for the lightweight reviewer dashboard.  It
returns plain dictionaries so the Streamlit rendering layer does not know SQL
or PostgreSQL details.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Mapping

from psycopg.types.json import Jsonb

from scripts.evaluation_auth import can_administer, can_review, hash_password, normalise_role, verify_password


DECISIONS = ("ALL", "PASS", "FAIL")
AGREEMENT_STATES = ("ALL", "AGREED", "DISAGREED", "UNJUDGED")
REVIEW_STATUSES = ("ACTIVE", "READY_FOR_REVIEW", "IN_REVIEW", "REVIEWED", "DISPUTED")


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
    durations = [
        float(row["duration_seconds"])
        for row in attempts
        if row.get("duration_seconds") is not None
    ]
    return {
        "total_attempts": total,
        "pass_count": passes,
        "pass_percentage": percentage(passes, total),
        "fail_count": fails,
        "fail_percentage": percentage(fails, total),
        "judged_count": len(judged),
        "agreement_count": agreements,
        "agreement_percentage": percentage(agreements, len(judged)),
        "average_duration_seconds": round(sum(durations) / len(durations), 1) if durations else 0.0,
    }


def _require_attempt_access(connection, attempt_id: int, user: Mapping[str, object]) -> None:
    """Enforce ownership, reviewer assignment, or administrator access."""
    role = normalise_role(user.get("role"))
    if can_administer(role):
        return
    if role == "TESTER":
        allowed = connection.execute(
            """SELECT 1
               FROM precheck_attempts a
               JOIN evaluation_sessions s ON s.id = a.session_id
               WHERE a.id = %s AND lower(s.tester_email) = lower(%s)""",
            (attempt_id, str(user.get("email") or "").strip()),
        ).fetchone()
        if allowed is None:
            raise PermissionError("attempt is not owned by this tester")
        return
    if not can_review(role):
        raise PermissionError("reviewer access required")
    allowed = connection.execute(
        """SELECT 1 FROM review_assignments
           WHERE precheck_attempt_id = %s AND reviewer_id = %s
             AND status <> 'REVOKED'""",
        (attempt_id, user.get("id")),
    ).fetchone()
    if allowed is None:
        raise PermissionError("attempt is not assigned to this reviewer")


def get_attempt_detail(
    connection, attempt_id: int, user: Mapping[str, object]
) -> dict[str, object] | None:
    """Return an authorized attempt, payload, findings, and file metadata."""
    _require_attempt_access(connection, attempt_id, user)
    cursor = connection.execute(
        """SELECT a.id AS attempt_id, a.session_id, a.case_id, a.system_decision,
                  a.started_at, a.completed_at,
                  EXTRACT(EPOCH FROM (a.completed_at - a.started_at)) AS duration_seconds,
                  a.result_payload, s.tester_email, s.tester_name, s.task_name,
                  j.judgement AS tester_judgement, j.explanation AS judgement_explanation,
                  j.recorded_at AS judgement_recorded_at
           """ + _BASE_FROM + " WHERE a.id = %s", (attempt_id,))
    detail = _row(cursor)
    if detail is None:
        return None

    files = _rows(connection.execute(
        """SELECT id, role, filename, mime_type, size_bytes, sha256, captured_at
           FROM evaluation_files WHERE precheck_attempt_id = %s ORDER BY id""",
        (attempt_id,),
    ))
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
    connection,
    attempt_id: int,
    judgement: str,
    explanation: str = "",
    reviewer_identity: str = "",
    rule_judgements: Mapping[str, tuple[str, str]] | None = None,
) -> None:
    """Record independent tester judgements without changing system_decision."""
    value = judgement.strip().upper()
    if value not in {"PASS", "FAIL"}:
        raise ValueError("judgement must be PASS or FAIL")
    normalized_rules = _normalise_rule_judgements(rule_judgements)
    with connection.transaction():
        connection.execute(
            """INSERT INTO tester_judgements (precheck_attempt_id, judgement, explanation)
               VALUES (%s, %s, %s)
               ON CONFLICT (precheck_attempt_id) DO UPDATE SET judgement = EXCLUDED.judgement,
                 explanation = EXCLUDED.explanation, recorded_at = CURRENT_TIMESTAMP""",
            (attempt_id, value, explanation.strip() or None),
        )
        for rule_id, (rule_value, rule_comment) in normalized_rules.items():
            connection.execute(
                """INSERT INTO tester_rule_judgements
                   (precheck_attempt_id, rule_id, judgement, comment)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (precheck_attempt_id, rule_id) DO UPDATE SET
                     judgement = EXCLUDED.judgement, comment = EXCLUDED.comment,
                     recorded_at = CURRENT_TIMESTAMP""",
                (attempt_id, rule_id, rule_value, rule_comment or None),
            )
        connection.execute(
            """INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
               SELECT session_id, id, 'tester_judgement_recorded', %s
               FROM precheck_attempts WHERE id = %s""",
            (Jsonb({
                "judgement": value,
                "reviewer_identity": reviewer_identity.strip(),
                "rule_count": len(normalized_rules),
            }), attempt_id),
        )


_RULE_JUDGEMENT_VALUES = {"CORRECT", "INCORRECT", "UNCLEAR", "NOT_APPLICABLE"}


def _normalise_rule_judgements(
    rule_judgements: Mapping[str, tuple[str, str]] | None,
) -> dict[str, tuple[str, str]]:
    """Validate and normalize per-rule judgements before opening a transaction."""
    normalized: dict[str, tuple[str, str]] = {}
    for raw_rule_id, raw_value in (rule_judgements or {}).items():
        rule_id = str(raw_rule_id).strip()
        if not rule_id:
            raise ValueError("rule_id must not be empty")
        try:
            raw_judgement, raw_comment = raw_value
        except (TypeError, ValueError):
            raise ValueError("rule judgement must contain a value and comment") from None
        rule_judgement = str(raw_judgement).strip().upper()
        if rule_judgement not in _RULE_JUDGEMENT_VALUES:
            raise ValueError("invalid rule judgement")
        normalized[rule_id] = (rule_judgement, str(raw_comment or "").strip())
    return normalized


def authenticate_user(connection, email: str, password: str) -> dict[str, object] | None:
    """Authenticate an active application user without exposing password data."""
    cursor = connection.execute(
        """SELECT id, email, display_name, password_hash, role
           FROM app_users WHERE lower(email) = lower(%s) AND active = TRUE""",
        (email.strip(),),
    )
    user = _row(cursor)
    if not user or not verify_password(password, str(user["password_hash"])):
        return None
    user.pop("password_hash", None)
    return user


def ensure_configured_admin(connection, email: str, password: str) -> int | None:
    """Create or refresh the local bootstrap administrator from private config."""
    if not email.strip() or not password:
        return None
    cursor = connection.execute("SELECT id FROM app_users WHERE lower(email) = lower(%s)", (email.strip(),))
    existing = cursor.fetchone()
    if existing:
        return int(existing[0])
    return create_user(connection, email, email, password, "ADMINISTRATOR")


def create_user(connection, email: str, display_name: str, password: str, role: str) -> int:
    """Create a user; only an administrator should expose this operation."""
    role = normalise_role(role)
    with connection.transaction():
        cursor = connection.execute(
            """INSERT INTO app_users (email, display_name, password_hash, role)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (email.strip(), display_name.strip(), hash_password(password), role),
        )
        return int(cursor.fetchone()[0])


def list_users(connection, role: str = "REVIEWER") -> list[dict[str, object]]:
    """List active users for administrator account and assignment management."""
    normalized = normalise_role(role)
    cursor = connection.execute(
        """SELECT id, email, display_name, role, active, created_at
           FROM app_users WHERE role = %s AND active = TRUE
           ORDER BY display_name, email""",
        (normalized,),
    )
    return _rows(cursor)


def assign_reviewer(connection, attempt_id: int, reviewer_id: int, administrator_id: int) -> None:
    """Assign an attempt to a reviewer and record the assignment event."""
    with connection.transaction():
        connection.execute(
            """INSERT INTO review_assignments
               (precheck_attempt_id, reviewer_id, assigned_by)
               VALUES (%s, %s, %s)
               ON CONFLICT (precheck_attempt_id, reviewer_id)
               DO UPDATE SET status = 'ASSIGNED', assigned_by = EXCLUDED.assigned_by""",
            (attempt_id, reviewer_id, administrator_id),
        )
        connection.execute(
            """INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
               SELECT session_id, id, 'reviewer_assigned', %s
               FROM precheck_attempts WHERE id = %s""",
            (Jsonb({"reviewer_id": reviewer_id, "assigned_by": administrator_id}), attempt_id),
        )
    refresh_review_status(connection, attempt_id)


def list_assignable_attempts(connection) -> list[dict[str, object]]:
    """List completed attempts that an administrator may assign."""
    cursor = connection.execute(
        """SELECT a.id AS attempt_id, a.system_decision, a.completed_at,
                  s.tester_email, s.tester_name
           FROM precheck_attempts a
           JOIN evaluation_sessions s ON s.id = a.session_id
           WHERE a.system_decision IS NOT NULL
           ORDER BY a.completed_at DESC NULLS LAST, a.id DESC"""
    )
    return _rows(cursor)


def get_review_status(connection, attempt_id: int) -> dict[str, object]:
    """Return the persisted review lifecycle status and reviewer counts."""
    cursor = connection.execute(
        """SELECT COALESCE(rs.status, 'ACTIVE') AS status,
                  (SELECT COUNT(*) FROM review_assignments
                   WHERE precheck_attempt_id = %s AND status <> 'REVOKED') AS assigned_count,
                  (SELECT COUNT(*) FROM reviewer_submissions
                   WHERE precheck_attempt_id = %s) AS submitted_count,
                  (SELECT COUNT(DISTINCT overall_judgement) FROM reviewer_submissions
                   WHERE precheck_attempt_id = %s) AS judgement_count
           FROM (SELECT 1) seed
           LEFT JOIN evaluation_review_status rs ON rs.precheck_attempt_id = %s""",
        (attempt_id, attempt_id, attempt_id, attempt_id),
    )
    row = _row(cursor)
    return row or {
        "status": "ACTIVE", "assigned_count": 0,
        "submitted_count": 0, "judgement_count": 0,
    }


def refresh_review_status(connection, attempt_id: int) -> str:
    """Recompute lifecycle status from assignments and independent submissions.

    A dispute is sticky until an administrator explicitly resolves it. This
    function never overwrites a resolved status, preserving the resolution
    decision while allowing new submissions to be audited separately.
    """
    counts = get_review_status(connection, attempt_id)
    current = str(counts["status"])
    if current == "DISPUTED":
        return current
    assigned = int(counts["assigned_count"] or 0)
    submitted = int(counts["submitted_count"] or 0)
    judgements = int(counts["judgement_count"] or 0)
    if judgements > 1:
        status = "DISPUTED"
    elif submitted == 0:
        status = "READY_FOR_REVIEW" if assigned else "ACTIVE"
    elif assigned and submitted < assigned:
        status = "IN_REVIEW"
    else:
        status = "REVIEWED"
    with connection.transaction():
        connection.execute(
            """INSERT INTO evaluation_review_status (precheck_attempt_id, status)
               VALUES (%s, %s)
               ON CONFLICT (precheck_attempt_id) DO UPDATE SET
                 status = EXCLUDED.status, updated_at = CURRENT_TIMESTAMP""",
            (attempt_id, status),
        )
    return status


def resolve_review_dispute(
    connection, attempt_id: int, administrator: Mapping[str, object], comment: str
) -> None:
    """Resolve a disputed attempt without changing reviewer submissions."""
    if not can_administer(normalise_role(administrator["role"])):
        raise PermissionError("administrator access required")
    explanation = comment.strip()
    if not explanation:
        raise ValueError("resolution comment must not be empty")
    with connection.transaction():
        connection.execute(
            """UPDATE evaluation_review_status
               SET status = 'REVIEWED', resolution_comment = %s,
                   resolved_by = %s, resolved_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE precheck_attempt_id = %s AND status = 'DISPUTED'""",
            (explanation, administrator["id"], attempt_id),
        )
        connection.execute(
            """INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
               SELECT session_id, id, 'review_dispute_resolved', %s
               FROM precheck_attempts WHERE id = %s""",
            (Jsonb({"administrator_id": administrator["id"], "comment": explanation}), attempt_id),
        )


def get_reviewer_submission(
    connection, attempt_id: int, reviewer_id: int
) -> dict[str, object] | None:
    """Return only the current reviewer's own submission, if one exists."""
    cursor = connection.execute(
        """SELECT id, overall_judgement, comment, submitted_at
           FROM reviewer_submissions
           WHERE precheck_attempt_id = %s AND reviewer_id = %s""",
        (attempt_id, reviewer_id),
    )
    return _row(cursor)


def get_rule_judgement_report(connection, attempt_id: int) -> list[dict[str, object]]:
    """Summarize independent reviewer judgements for each finding on an attempt."""
    cursor = connection.execute(
        """SELECT rr.rule_id,
                  COUNT(*) AS judgement_count,
                  COUNT(DISTINCT rr.judgement) AS distinct_judgement_count,
                  COUNT(*) FILTER (WHERE rr.judgement = 'CORRECT') AS correct_count,
                  COUNT(*) FILTER (WHERE rr.judgement = 'INCORRECT') AS incorrect_count,
                  COUNT(*) FILTER (WHERE rr.judgement = 'UNCLEAR') AS unclear_count,
                  COUNT(*) FILTER (WHERE rr.judgement = 'NOT_APPLICABLE') AS not_applicable_count,
                  (COUNT(DISTINCT rr.judgement) > 1) AS disagreement
           FROM reviewer_rule_judgements rr
           JOIN reviewer_submissions rs ON rs.id = rr.submission_id
           WHERE rs.precheck_attempt_id = %s
           GROUP BY rr.rule_id
           ORDER BY rr.rule_id""",
        (attempt_id,),
    )
    return _rows(cursor)


def get_cross_attempt_review_report(connection) -> dict[str, object]:
    """Return aggregate reviewer agreement metrics across all completed attempts."""
    cursor = connection.execute(
        """WITH review_rows AS (
                 SELECT rs.precheck_attempt_id, rs.overall_judgement, a.system_decision
                 FROM reviewer_submissions rs
                 JOIN precheck_attempts a ON a.id = rs.precheck_attempt_id
                 WHERE a.system_decision IS NOT NULL
             ), rule_groups AS (
                 SELECT rs.precheck_attempt_id, rr.rule_id,
                        COUNT(*) AS judgement_count,
                        COUNT(DISTINCT rr.judgement) AS distinct_judgement_count
                 FROM reviewer_rule_judgements rr
                 JOIN reviewer_submissions rs ON rs.id = rr.submission_id
                 JOIN precheck_attempts a ON a.id = rs.precheck_attempt_id
                 WHERE a.system_decision IS NOT NULL
                 GROUP BY rs.precheck_attempt_id, rr.rule_id
             )
             SELECT
                 COUNT(DISTINCT review_rows.precheck_attempt_id) AS reviewed_attempt_count,
                 COUNT(*) AS reviewer_submission_count,
                 COUNT(*) FILTER (WHERE overall_judgement = system_decision) AS overall_agreement_count,
                 COUNT(*) FILTER (WHERE overall_judgement <> system_decision) AS overall_disagreement_count,
                 (SELECT COUNT(*) FROM evaluation_review_status WHERE status = 'DISPUTED') AS disputed_attempt_count,
                 (SELECT COUNT(*) FROM reviewer_rule_judgements rr
                    JOIN reviewer_submissions rs ON rs.id = rr.submission_id
                    JOIN precheck_attempts a ON a.id = rs.precheck_attempt_id
                    WHERE a.system_decision IS NOT NULL) AS rule_judgement_count,
                 (SELECT COUNT(*) FROM reviewer_rule_judgements rr
                    JOIN reviewer_submissions rs ON rs.id = rr.submission_id
                    JOIN precheck_attempts a ON a.id = rs.precheck_attempt_id
                    WHERE a.system_decision IS NOT NULL AND rr.judgement = 'UNCLEAR') AS unclear_count,
                 (SELECT COUNT(*) FROM reviewer_rule_judgements rr
                    JOIN reviewer_submissions rs ON rs.id = rr.submission_id
                    JOIN precheck_attempts a ON a.id = rs.precheck_attempt_id
                    WHERE a.system_decision IS NOT NULL AND rr.judgement = 'NOT_APPLICABLE') AS not_applicable_count,
                 (SELECT COUNT(*) FROM rule_groups) AS rule_group_count,
                 (SELECT COUNT(*) FROM rule_groups WHERE distinct_judgement_count > 1) AS rule_disagreement_count
             FROM review_rows"""
    )
    row = _row(cursor) or {}
    percentage = lambda count, denominator: round((count / denominator) * 100, 1) if denominator else 0.0
    submissions = int(row.get("reviewer_submission_count") or 0)
    rule_groups = int(row.get("rule_group_count") or 0)
    return {
        "reviewed_attempt_count": int(row.get("reviewed_attempt_count") or 0),
        "reviewer_submission_count": submissions,
        "overall_agreement_count": int(row.get("overall_agreement_count") or 0),
        "overall_disagreement_count": int(row.get("overall_disagreement_count") or 0),
        "overall_agreement_percentage": percentage(int(row.get("overall_agreement_count") or 0), submissions),
        "disputed_attempt_count": int(row.get("disputed_attempt_count") or 0),
        "rule_judgement_count": int(row.get("rule_judgement_count") or 0),
        "unclear_count": int(row.get("unclear_count") or 0),
        "not_applicable_count": int(row.get("not_applicable_count") or 0),
        "rule_group_count": rule_groups,
        "rule_disagreement_count": int(row.get("rule_disagreement_count") or 0),
        "rule_disagreement_percentage": percentage(int(row.get("rule_disagreement_count") or 0), rule_groups),
    }


def list_review_queue(connection, user: Mapping[str, object]) -> list[dict[str, object]]:
    """Return only attempts the authenticated reviewer is allowed to inspect."""

    role = normalise_role(user["role"])

    if not can_review(role):
        raise PermissionError("reviewer access required")
    if can_administer(role):
        clause, params = "", []
        assignment_join = "LEFT JOIN review_assignments ra ON ra.precheck_attempt_id = a.id"
    else:

        clause, params = "WHERE ra.reviewer_id = %s AND ra.status <> 'REVOKED'", [user["id"]]
        assignment_join = "JOIN review_assignments ra ON ra.precheck_attempt_id = a.id"
    cursor = connection.execute(
        """SELECT a.id AS attempt_id, a.system_decision, a.started_at, a.completed_at,
                  ra.status AS assignment_status, ra.reviewer_id,
                  COALESCE(rev.status, 'ACTIVE') AS review_status,
                  s.tester_email, s.tester_name
           FROM precheck_attempts a
           JOIN evaluation_sessions s ON s.id = a.session_id
           """ + assignment_join + """
           LEFT JOIN evaluation_review_status rev ON rev.precheck_attempt_id = a.id
           """ + clause + " ORDER BY a.started_at DESC, a.id DESC",
        params,
    )

    return _rows(cursor)


def list_review_queue_page(
    connection,
    user: Mapping[str, object],
    filters: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return one filtered page of attempts visible to the reviewer."""
    role = normalise_role(user["role"])
    if not can_review(role):
        raise PermissionError("reviewer access required")
    filters = filters or {}
    page = max(1, int(filters.get("page", 1)))
    page_size = min(100, max(1, int(filters.get("page_size", 20))))
    conditions = ["a.system_decision IS NOT NULL"]
    params: list[object] = []
    if can_administer(role):
        assignment_join = "LEFT JOIN review_assignments ra ON ra.precheck_attempt_id = a.id"
    else:
        assignment_join = "JOIN review_assignments ra ON ra.precheck_attempt_id = a.id"
        conditions.append("ra.reviewer_id = %s AND ra.status <> 'REVOKED'")
        params.append(user["id"])
    decision = str(filters.get("decision", "ALL")).upper()
    if decision in {"PASS", "FAIL"}:
        conditions.append("a.system_decision = %s")
        params.append(decision)
    review_status = str(filters.get("review_status", "ALL")).upper()
    if review_status in REVIEW_STATUSES:
        conditions.append("COALESCE(rev.status, 'ACTIVE') = %s")
        params.append(review_status)
    tester = str(filters.get("tester", "")).strip()
    if tester:
        conditions.append("(s.tester_email ILIKE %s OR COALESCE(s.tester_name, '') ILIKE %s)")
        params.extend((f"%{tester}%", f"%{tester}%"))
    where = " AND ".join(conditions)
    count_cursor = connection.execute(
        """SELECT COUNT(DISTINCT a.id)
           FROM precheck_attempts a
           JOIN evaluation_sessions s ON s.id = a.session_id
           """ + assignment_join + """
           LEFT JOIN evaluation_review_status rev ON rev.precheck_attempt_id = a.id
           WHERE """ + where,
        params,
    )
    total = int(count_cursor.fetchone()[0])
    offset = (page - 1) * page_size
    rows = _rows(connection.execute(
        """SELECT DISTINCT a.id AS attempt_id, a.system_decision, a.started_at, a.completed_at,
                  EXTRACT(EPOCH FROM (a.completed_at - a.started_at)) AS duration_seconds,
                  ra.status AS assignment_status, ra.reviewer_id,
                  COALESCE(rev.status, 'ACTIVE') AS review_status,
                  s.tester_email, s.tester_name
           FROM precheck_attempts a
           JOIN evaluation_sessions s ON s.id = a.session_id
           """ + assignment_join + """
           LEFT JOIN evaluation_review_status rev ON rev.precheck_attempt_id = a.id
           WHERE """ + where + " ORDER BY a.started_at DESC, a.id DESC LIMIT %s OFFSET %s",
        params + [page_size, offset],
    ))
    return {
        "attempts": rows,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


def submit_reviewer_judgement(

    connection, attempt_id: int, reviewer: Mapping[str, object], overall: str,
    comment: str = "", rule_judgements: Mapping[str, tuple[str, str]] | None = None,
) -> None:
    """Store an independent reviewer submission after assignment authorization."""
    value = overall.strip().upper()
    if value not in {"PASS", "FAIL"}:
        raise ValueError("overall judgement must be PASS or FAIL")
    role = normalise_role(reviewer["role"])
    if not can_review(role):
        raise PermissionError("reviewer access required")
    normalized_rules = _normalise_rule_judgements(rule_judgements)
    with connection.transaction():
        allowed = connection.execute(
            """SELECT 1 FROM review_assignments
               WHERE precheck_attempt_id = %s AND reviewer_id = %s
                 AND status <> 'REVOKED'""",
            (attempt_id, reviewer["id"]),
        ).fetchone()
        if allowed is None and not can_administer(role):
            raise PermissionError("attempt is not assigned to this reviewer")
        cursor = connection.execute(
            """INSERT INTO reviewer_submissions
               (precheck_attempt_id, reviewer_id, overall_judgement, comment)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (precheck_attempt_id, reviewer_id) DO UPDATE SET
                 overall_judgement = EXCLUDED.overall_judgement,
                 comment = EXCLUDED.comment, submitted_at = CURRENT_TIMESTAMP
               RETURNING id""",
            (attempt_id, reviewer["id"], value, comment.strip() or None),
        )
        submission_id = int(cursor.fetchone()[0])
        for rule_id, (normalized, rule_comment) in normalized_rules.items():
            connection.execute(
                """INSERT INTO reviewer_rule_judgements
                   (submission_id, rule_id, judgement, comment) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (submission_id, rule_id) DO UPDATE SET
                     judgement = EXCLUDED.judgement, comment = EXCLUDED.comment""",
                (submission_id, rule_id, normalized, rule_comment.strip() or None),
            )
        connection.execute(
            """UPDATE review_assignments SET status = 'SUBMITTED'
               WHERE precheck_attempt_id = %s AND reviewer_id = %s""",
            (attempt_id, reviewer["id"]),
        )
        connection.execute(
            """INSERT INTO evaluation_review_status (precheck_attempt_id, status)
               VALUES (%s, 'IN_REVIEW')
               ON CONFLICT (precheck_attempt_id) DO NOTHING""",
            (attempt_id,),
        )
        connection.execute(
            """INSERT INTO evaluation_events (session_id, precheck_attempt_id, event_type, metadata)
               SELECT session_id, id, 'reviewer_judgement_submitted', %s
               FROM precheck_attempts WHERE id = %s""",
            (Jsonb({"reviewer_id": reviewer["id"], "overall": value}), attempt_id),
        )
    refresh_review_status(connection, attempt_id)


def get_original_file(
    connection, attempt_id: int, role: str, user: Mapping[str, object]
) -> dict[str, object] | None:
    """Fetch one original file after enforcing attempt authorization."""
    if role not in {"ecn", "bom", "other"}:
        raise ValueError("role must be ecn, bom, or other")
    _require_attempt_access(connection, attempt_id, user)
    cursor = connection.execute(
        """SELECT filename, mime_type, size_bytes, sha256, captured_at, content
           FROM evaluation_files WHERE precheck_attempt_id = %s AND role = %s
           ORDER BY id LIMIT 1""", (attempt_id, role))
    return _row(cursor)
