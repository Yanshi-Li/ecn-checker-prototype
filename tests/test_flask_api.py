
"""Con  tract tests for the Flask endpoints used by the React frontend."""

from io import BytesIO
from pathlib import Path

from scripts import app as flask_app

app = flask_app.app


def test_health_endpoint_reports_the_react_api_is_available():
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_precheck_uses_the_staged_pipeline_for_a_generic_ecn_filename(monkeypatch):
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

    response = client.post(
        "/api/precheck",
        data={
            "tester_email": "tester@example.com",
            "ecn": (BytesIO(b"change_notice_number\nECN-4079118\n"), "ECN_4079118.csv"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["decision"] == "FAIL"
    assert response.get_json()["findings"][0]["rule"] == "H01"
    assert Path(paths[0]).name.startswith("ECN_4079118_")
    assert paths[1] is None
