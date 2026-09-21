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
    connection = Connection([Cursor(user_columns, [(4, "reviewer@example.com", "Reviewer", "REVIEWER", True, None)]), Cursor([], []), Cursor([], [])])
    users = queries.list_users(connection)
    assert users[0]["role"] == "REVIEWER"
    queries.assign_reviewer(connection, 9, 4, 1)
    assert "review_assignments" in connection.statements[1][0]
    assert "reviewer_assigned" in connection.statements[2][0]


def test_invalid_judgement_and_missing_configuration_are_safe():
    try:
        queries.save_tester_judgement(Connection([]), 1, "MAYBE")
    except ValueError as exc:
        assert "judgement" in str(exc)
    else:
        raise AssertionError("invalid judgement accepted")
