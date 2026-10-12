from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from scripts import precheck_workflow


def _upload(contents: bytes, filename: str, role: str) -> FileStorage:
    return FileStorage(
        stream=BytesIO(contents),
        filename=filename,
        content_type="text/csv",
        headers={"X-Upload-Role": role},
    )


def _packet(decision: str = "PASS") -> dict:
    return {
        "gate": {
            "decision": decision,
            "blockers": [
                {"rule_id": "H01", "severity": "ERROR", "message": "Required field is missing."}
            ] if decision == "FAIL" else [],
            "part_issues": [],
            "conflict_alerts": [],
            "warnings": [
                {"rule_id": "W01", "severity": "WARNING", "message": "Review wording."}
            ],
        }
    }


def test_precheck_workflow_validates_persists_and_shapes_the_result(monkeypatch):
    started_at = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 10, 11, 12, 0, 4, tzinfo=timezone.utc)
    clock_values = iter((started_at, completed_at))
    received = {}

    monkeypatch.setattr(precheck_workflow, "_utc_now", lambda: next(clock_values))

    def fake_run_precheck(ecn_path, bom_path):
        received["paths"] = (ecn_path, bom_path)
        received["contents"] = (Path(ecn_path).read_bytes(), Path(bom_path).read_bytes())
        return _packet("FAIL")

    def fake_persist(tester_email, tester_name, packet, uploaded_files, **timing):
        received["persisted"] = (tester_email, tester_name, packet, uploaded_files, timing)
        return {"saved": True, "attempt_id": 41, "duration_seconds": 4.0}

    monkeypatch.setattr(precheck_workflow, "run_precheck", fake_run_precheck)
    monkeypatch.setattr(precheck_workflow, "_persist_precheck", fake_persist)

    result = precheck_workflow.run_precheck_workflow(
        _upload(b"ecn source", "ECN_4079118.csv", "ecn"),
        _upload(b"bom source", "BOM_4079118.csv", "bom"),
        tester_email="tester@example.com",
        tester_name="Evaluation Tester",
        source_status="COMPLETED",
    )

    assert result["decision"] == "FAIL"
    assert result["summary"] == {"total_files": 2, "total_issues": 2, "errors": 1, "warnings": 1}
    assert result["findings"][0]["rule"] == "H01"
    assert result["persistence"] == {"saved": True, "attempt_id": 41, "duration_seconds": 4.0}
    assert received["contents"] == (b"ecn source", b"bom source")
    assert received["persisted"][0:2] == ("tester@example.com", "Evaluation Tester")
    assert received["persisted"][3][0]["role"] == "ecn"
    assert received["persisted"][3][1]["role"] == "bom"
    assert received["persisted"][4] == {
        "source_status": "COMPLETED",
        "started_at": started_at,
        "completed_at": completed_at,
    }
    assert all(not Path(path).exists() for path in received["paths"])


def test_precheck_workflow_cleans_temporary_uploads_when_validation_fails(monkeypatch):
    temporary_paths = []

    def fail_validation(ecn_path, bom_path):
        temporary_paths.extend(path for path in (ecn_path, bom_path) if path)
        raise RuntimeError("validation failed")

    monkeypatch.setattr(precheck_workflow, "run_precheck", fail_validation)
    monkeypatch.setattr(precheck_workflow, "_persist_precheck", lambda *args, **kwargs: pytest.fail("must not persist"))

    with pytest.raises(RuntimeError, match="validation failed"):
        precheck_workflow.run_precheck_workflow(
            _upload(b"ecn source", "ECN.csv", "ecn"),
            None,
            tester_email="tester@example.com",
            tester_name="Evaluation Tester",
            source_status="DRAFT",
        )

    assert len(temporary_paths) == 1
    assert all(not Path(path).exists() for path in temporary_paths)
