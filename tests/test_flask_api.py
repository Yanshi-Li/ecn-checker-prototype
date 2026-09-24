
"""Contract tests for the Flask endpoints used by the React frontend."""

from io import BytesIO
from pathlib import Path

from scripts import app as flask_app

app = flask_app.app


def test_health_endpoint_reports_the_react_api_is_available():
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_login_creates_a_tester_session(monkeypatch):
    connection = object()
    monkeypatch.setattr(flask_app, "connect_evaluation_db", lambda: _ConnectionContext(connection))
    monkeypatch.setattr(flask_app, "initialise_schema", lambda _: None)
    monkeypatch.setattr(flask_app.evaluation_queries, "ensure_configured_admin", lambda *_: None)
    monkeypatch.setattr(
        flask_app.evaluation_queries,
        "authenticate_user",
        lambda *_: {"id": 4, "email": "tester@example.com", "display_name": "Test User", "role": "TESTER"},
    )
    client = app.test_client()

    response = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "correct password"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "user": {"id": 4, "email": "tester@example.com", "display_name": "Test User", "role": "TESTER"},
    }
    with client.session_transaction() as session:
        assert session["user"] == response.get_json()["user"]


def test_precheck_requires_a_signed_in_tester():
    client = app.test_client()

    response = client.post("/api/precheck", data={}, content_type="multipart/form-data")

    assert response.status_code == 401
    assert response.get_json() == {"error": "Sign in before running a pre-check."}


def test_administrator_can_run_the_staged_pipeline_for_a_generic_ecn_filename(monkeypatch):
    paths = []

    def fake_run_precheck(ecn_path, bom_path=None):
        paths.extend([ecn_path, bom_path])
        return {
            "gate": {
                "decision": "FAIL",
                "blockers": [
                    {"rule_id": "H01", "severity": "ERROR", "message": "Required ECN field is missing."}
                ],
                "part_issues": [],
                "conflict_alerts": [],
                "warnings": [],
            }
        }

    monkeypatch.setattr(flask_app, "run_precheck", fake_run_precheck)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "admin@example.com", "display_name": "Admin User", "role": "ADMINISTRATOR"}

    response = client.post(
        "/api/precheck",
        data={
            "ecn": (BytesIO(b"change_notice_number\nECN-4079118\n"), "ECN_4079118.csv"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["decision"] == "FAIL"
    assert response.get_json()["findings"][0]["rule"] == "H01"
    assert Path(paths[0]).name.startswith("ECN_4079118_")
    assert paths[1] is None


class _ConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *args):
        return False


def test_admin_evaluation_summary_is_protected_and_returns_metrics(monkeypatch):
    connection = object()
    monkeypatch.setattr(flask_app, "connect_evaluation_db", lambda: _ConnectionContext(connection))
    monkeypatch.setattr(flask_app, "initialise_schema", lambda _: None)
    monkeypatch.setattr(
        flask_app.evaluation_queries,
        "get_evaluation_summary",
        lambda *_: {"total_attempts": 2, "pass_percentage": 50.0, "fail_percentage": 50.0},
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 1, "email": "admin@example.com", "role": "ADMINISTRATOR"}

    response = client.get("/api/admin/evaluation-summary?decision=PASS")

    assert response.status_code == 200
    assert response.get_json()["pass_percentage"] == 50.0


def test_admin_evaluation_summary_rejects_non_administrators():
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "reviewer@example.com", "role": "REVIEWER"}

    response = client.get("/api/admin/evaluation-summary")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Administrator access is required."}


def test_reviewer_queue_returns_only_authorized_queue(monkeypatch):
    connection = object()
    monkeypatch.setattr(flask_app, "connect_evaluation_db", lambda: _ConnectionContext(connection))
    monkeypatch.setattr(flask_app, "initialise_schema", lambda _: None)
    monkeypatch.setattr(
        flask_app.evaluation_queries,
        "list_review_queue",
        lambda connection, user: [{"attempt_id": 17, "system_decision": "FAIL"}],
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "reviewer@example.com", "role": "REVIEWER"}

    response = client.get("/api/reviewer/queue")

    assert response.status_code == 200
    assert response.get_json() == {"attempts": [{"attempt_id": 17, "system_decision": "FAIL"}]}


def test_reviewer_detail_returns_query_layer_result(monkeypatch):
    connection = object()
    detail = {"attempt_id": 17, "system_decision": "FAIL", "findings": []}
    monkeypatch.setattr(flask_app, "connect_evaluation_db", lambda: _ConnectionContext(connection))
    monkeypatch.setattr(flask_app.evaluation_queries, "get_attempt_detail", lambda *_: detail)
    monkeypatch.setattr(flask_app.evaluation_queries, "get_reviewer_submission", lambda *_: None)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "reviewer@example.com", "role": "REVIEWER"}

    response = client.get("/api/reviewer/attempts/17")

    assert response.status_code == 200
    assert response.get_json() == {**detail, "reviewer_submission": None}


def test_reviewer_judgement_validates_and_persists_per_rule_values(monkeypatch):
    connection = object()
    submitted = {}
    monkeypatch.setattr(flask_app, "connect_evaluation_db", lambda: _ConnectionContext(connection))
    monkeypatch.setattr(
        flask_app.evaluation_queries,
        "submit_reviewer_judgement",
        lambda *args: submitted.update(args=args),
    )
    monkeypatch.setattr(
        flask_app.evaluation_queries,
        "get_review_status",
        lambda *_: {"status": "REVIEWED"},
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "reviewer@example.com", "role": "REVIEWER"}

    response = client.post(
        "/api/reviewer/attempts/17/judgement",
        json={
            "judgement": "PASS",
            "comment": "The result is understandable.",
            "rule_judgements": {"H01": {"judgement": "CORRECT", "comment": "Confirmed."}},
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"saved": True, "review_status": {"status": "REVIEWED"}}
    assert submitted["args"][1:] == (
        17,
        {"id": 4, "email": "reviewer@example.com", "role": "REVIEWER"},
        "PASS",
        "The result is understandable.",
        {"H01": ("CORRECT", "Confirmed.")},
    )


def test_reviewer_endpoints_reject_testers():
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "tester@example.com", "role": "TESTER"}

    response = client.get("/api/reviewer/queue")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Reviewer or administrator access is required."}


def test_notification_allows_a_pass_result_to_be_sent_to_the_next_checker(monkeypatch):
    sent = {}
    connection = object()

    monkeypatch.setattr(flask_app, "connect_evaluation_db", lambda: _ConnectionContext(connection))
    monkeypatch.setattr(
        flask_app.evaluation_queries,
        "get_attempt_detail",
        lambda *_: {"payload": {"packet": {"gate": {"decision": "PASS"}}}},
    )
    monkeypatch.setattr(
        flask_app,
        "send_validation_email",
        lambda packet, recipient: sent.update(packet=packet, recipient=recipient)
        or {"sent": True, "message": f"Validation report sent to {recipient}."},
    )
    recorded = []
    monkeypatch.setattr(flask_app, "record_notification_attempt", lambda *args: recorded.append(args))
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "creator@example.com", "display_name": "Creator", "role": "TESTER"}

    response = client.post(
        "/api/notification",
        json={
            "attempt_id": 17,
            "recipient": "next.checker@example.com",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "sent": True,
        "message": "Validation report sent to next.checker@example.com.",
    }
    assert sent["recipient"] == "next.checker@example.com"
    assert recorded[0][2:] == ("validation_report", "next.checker@example.com", "sent", "Validation report sent to next.checker@example.com.")


def test_notification_rejects_sending_a_failed_result_to_someone_other_than_the_tester(monkeypatch):
    connection = object()

    monkeypatch.setattr(flask_app, "connect_evaluation_db", lambda: _ConnectionContext(connection))
    monkeypatch.setattr(
        flask_app.evaluation_queries,
        "get_attempt_detail",
        lambda *_: {"payload": {"packet": {"gate": {"decision": "FAIL"}}}},
    )
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = {"id": 4, "email": "creator@example.com", "display_name": "Creator", "role": "TESTER"}

    response = client.post(
        "/api/notification",
        json={
            "attempt_id": 18,
            "recipient": "next.checker@example.com",
        },
    )

    assert response.status_code == 403
    assert response.get_json() == {"error": "Failed results can only be emailed to the tester."}
