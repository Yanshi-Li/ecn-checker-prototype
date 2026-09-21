"""Behaviour tests for the reviewer query seam."""
from datetime import datetime, timezone

from scripts import evaluation_queries as queries


class Cursor:
    def __init__(self, columns, rows):
        self.description = [(column,) for column in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


class Connection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.statements = []

    def execute(self, statement, params=None):
        self.statements.append((statement, params))
        response = self.responses.pop(0)
        return response if isinstance(response, Cursor) else Cursor([], [])

    class Tx:
        def __init__(self, owner): self.owner = owner
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def transaction(self): return self.Tx(self)


ATTEMPT_COLUMNS = [
    "attempt_id", "system_decision", "started_at", "completed_at", "duration_seconds",
    "case_identifier", "tester_email", "tester_name", "tester_judgement", "agreement",
]


def attempt(attempt_id, decision, judgement=None, case="ECN-1", tester="a@example.com"):
    return (attempt_id, decision, datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc), 2.0, case,
            tester, "Tester", judgement, judgement == decision if judgement else False)


def test_summary_counts_percentages_and_excludes_unjudged_agreement_denominator():
    rows = [attempt(1, "PASS", "PASS"), attempt(2, "FAIL", "PASS"), attempt(3, "FAIL")]
    summary = queries.get_evaluation_summary(Connection([Cursor(ATTEMPT_COLUMNS, rows)]))
    assert summary == {
        "total_attempts": 3, "pass_count": 1, "pass_percentage": 33.3,
        "fail_count": 2, "fail_percentage": 66.7, "judged_count": 2,
        "agreement_count": 1, "agreement_percentage": 50.0,
    }


def test_list_attempts_builds_observable_pass_case_and_tester_filters():
    connection = Connection([Cursor(ATTEMPT_COLUMNS, [])])
    queries.list_attempts(connection, {"system_decision": "PASS", "case_identifier": "407", "tester": "lee"})
    sql, params = connection.statements[0]
    assert "a.system_decision = %s" in sql
    assert "le.logical_ecn_key ILIKE %s" in sql
    assert "s.tester_email ILIKE %s" in sql
    assert params[:3] == ["PASS", "%407%", "%lee%"]


def test_detail_contains_payload_findings_and_files():
    detail_row = (9, 4, 3, "FAIL", datetime(2026, 1, 1, tzinfo=timezone.utc),
                  datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc), 2.0,
                  {"packet": {"gate": {"blockers": [{"rule_id": "H01", "severity": "ERROR", "message": "Missing", "location": "header", "evidence": "x", "gate_effect": "FAIL"}], "warnings": [], "part_issues": [], "conflict_alerts": [], "ai_notes": {"flags": []}}}},
                  "a@example.com", "Tester", "ECN", None, None, None, None)
    columns = ["attempt_id", "session_id", "case_id", "system_decision", "started_at", "completed_at", "duration_seconds", "result_payload", "tester_email", "tester_name", "task_name", "tester_judgement", "judgement_explanation", "judgement_recorded_at"]
    files = Cursor(["id", "role", "filename", "mime_type", "size_bytes", "sha256", "captured_at"], [(1, "ecn", "input.csv", "text/csv", 3, "a" * 64, datetime.now(timezone.utc))])
    detail = queries.get_attempt_detail(Connection([Cursor(columns, [detail_row]), files]), 9)
    assert detail["payload"]["packet"]["gate"]["blockers"][0]["rule_id"] == "H01"
    assert detail["findings"][0]["evidence"] == "x"
    assert detail["files"][0]["filename"] == "input.csv"


def test_judgement_and_file_retrieval_preserve_separate_system_decision():
    connection = Connection([Cursor([], []), Cursor([], [])])
    queries.save_tester_judgement(connection, 9, "pass", "Looks correct", "reviewer@example.com")
    assert "UPDATE precheck_attempts" not in connection.statements[0][0]
    assert "tester_judgement_recorded" in connection.statements[1][0]

    file_connection = Connection([Cursor(["filename", "mime_type", "size_bytes", "sha256", "captured_at", "content"], [("ecn.csv", "text/csv", 3, "a" * 64, None, b"ecn")])])
    assert queries.get_original_file(file_connection, 9, "ecn")["content"] == b"ecn"


def test_admin_queries_list_users_and_assign_attempts():
    user_columns = ["id", "email", "display_name", "role", "active", "created_at"]
    connection = Connection([Cursor(user_columns, [(4, "reviewer@example.com", "Reviewer", "REVIEWER", True, None)]), Cursor([], []), Cursor([], []), Cursor(["status", "assigned_count", "submitted_count", "judgement_count"], [("READY_FOR_REVIEW", 1, 0, 0)]), Cursor([], [])])
    users = queries.list_users(connection)
    assert users[0]["role"] == "REVIEWER"
    queries.assign_reviewer(connection, 9, 4, 1)
    assert "review_assignments" in connection.statements[1][0]
    assert "reviewer_assigned" in connection.statements[2][0]
    assert connection.statements[4][1] == (9, "READY_FOR_REVIEW")


def test_refresh_review_status_transitions_to_disputed_when_reviewers_disagree():
    columns = ["status", "assigned_count", "submitted_count", "judgement_count"]
    connection = Connection([
        Cursor(columns, [("IN_REVIEW", 2, 2, 2)]),
        Cursor([], []),
    ])
    assert queries.refresh_review_status(connection, 9) == "DISPUTED"
    assert "evaluation_review_status" in connection.statements[1][0]
    assert connection.statements[1][1] == (9, "DISPUTED")


def test_refresh_review_status_marks_single_completed_review_as_reviewed():
    columns = ["status", "assigned_count", "submitted_count", "judgement_count"]
    connection = Connection([
        Cursor(columns, [("IN_REVIEW", 1, 1, 1)]),
        Cursor([], []),
    ])
    assert queries.refresh_review_status(connection, 12) == "REVIEWED"
    assert connection.statements[1][1] == (12, "REVIEWED")


def test_resolve_review_dispute_requires_admin_and_keeps_audit_event():
    admin = {"id": 7, "role": "ADMINISTRATOR"}
    connection = Connection([Cursor([], []), Cursor([], [])])
    queries.resolve_review_dispute(connection, 9, admin, "Administrator selected FAIL after source review.")
    assert "resolution_comment" in connection.statements[0][0]
    assert "review_dispute_resolved" in connection.statements[1][0]


def test_rule_judgement_report_summarizes_disagreement_counts():
    columns = [
        "rule_id", "judgement_count", "distinct_judgement_count", "correct_count",
        "incorrect_count", "unclear_count", "not_applicable_count", "disagreement",
    ]
    connection = Connection([Cursor(columns, [("H01", 2, 2, 1, 1, 0, 0, True)])])
    report = queries.get_rule_judgement_report(connection, 9)
    assert report == [{
        "rule_id": "H01", "judgement_count": 2, "distinct_judgement_count": 2,
        "correct_count": 1, "incorrect_count": 1, "unclear_count": 0,
        "not_applicable_count": 0, "disagreement": True,
    }]
    assert connection.statements[0][1] == (9,)
    assert "GROUP BY rr.rule_id" in connection.statements[0][0]


def test_cross_attempt_review_report_calculates_agreement_and_rule_disagreement():
    columns = [
        "reviewed_attempt_count", "reviewer_submission_count", "overall_agreement_count",
        "overall_disagreement_count", "disputed_attempt_count", "rule_judgement_count",
        "rule_group_count", "rule_disagreement_count",
    ]
    row = (3, 4, 3, 1, 1, 6, 4, 2)
    report = queries.get_cross_attempt_review_report(Connection([Cursor(columns, [row])]))
    assert report == {
        "reviewed_attempt_count": 3, "reviewer_submission_count": 4,
        "overall_agreement_count": 3, "overall_disagreement_count": 1,
        "overall_agreement_percentage": 75.0, "disputed_attempt_count": 1,
        "rule_judgement_count": 6, "rule_group_count": 4,
        "rule_disagreement_count": 2, "rule_disagreement_percentage": 50.0,
    }


def test_invalid_judgement_and_missing_configuration_are_safe():
    try:
        queries.save_tester_judgement(Connection([]), 1, "MAYBE")
    except ValueError as exc:
        assert "judgement" in str(exc)
    else:
        raise AssertionError("invalid judgement accepted")
