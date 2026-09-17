import json
import zipfile
from pathlib import Path

import pytest

from scripts.evaluation_bundle import (
    BUNDLE_VERSION,
    BundleError,
    export_evaluation_bundle,
    import_evaluation_bundle,
)


class RecordingStore:
    def __init__(self):
        self.records = []

    def import_snapshot(self, snapshot, files):
        self.records.append((snapshot, files))
        return len(self.records)


def _snapshot():
    return {
        "case_id": "ECN-1:BOM-1",
        "decision": "FAIL",
        "packet": {"gate": {"decision": "FAIL", "blockers": [{"rule_id": "H01"}]}},
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:01+00:00",
        "files": [
            {"role": "ecn", "filename": "ECN-1.csv", "mime_type": "text/csv", "bytes": b"ecn"},
            {"role": "bom", "filename": "BOM-1.csv", "mime_type": "text/csv", "bytes": b"bom"},
        ],
    }


def test_export_writes_versioned_manifest_result_and_original_files(tmp_path):
    bundle = export_evaluation_bundle([_snapshot()], tmp_path / "evaluation-batch-1.zip")

    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == BUNDLE_VERSION
        assert manifest["cases"][0]["case_id"] == "ECN-1:BOM-1"
        assert archive.read("cases/ECN-1_BOM-1/result.json")
        assert archive.read("cases/ECN-1_BOM-1/ECN-1.csv") == b"ecn"
        assert archive.read("cases/ECN-1_BOM-1/BOM-1.csv") == b"bom"


def test_import_verifies_hashes_and_is_idempotent(tmp_path):
    bundle = export_evaluation_bundle([_snapshot()], tmp_path / "bundle.zip")
    store = RecordingStore()

    assert import_evaluation_bundle(bundle, store) == [1]
    assert import_evaluation_bundle(bundle, store) == []
    assert len(store.records) == 1


def test_import_rejects_tampered_file_before_store_write(tmp_path):
    bundle = export_evaluation_bundle([_snapshot()], tmp_path / "bundle.zip")
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(bundle) as source, zipfile.ZipFile(tampered, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.endswith("ECN-1.csv"):
                data = b"tampered"
            target.writestr(item, data)

    with pytest.raises(BundleError, match="hash"):
        import_evaluation_bundle(tampered, RecordingStore())
