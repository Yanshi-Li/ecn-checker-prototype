"""Contract tests for the Flask endpoints used by the React frontend."""

from scripts.app import app


def test_health_endpoint_reports_the_react_api_is_available():
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
