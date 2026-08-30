import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("ecn_checker", ROOT / "scripts" / "ecn_checker.py")
ecn_checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecn_checker)


def _make_csv(headers: list, rows: list) -> str:
    import io, csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue()


def test_ecn_c006_obsolete_new_part():
    """ECN-C-006: replacing with an OBSOLETE part should raise an error."""
    changes_csv = _make_csv(
        ["ecn_number", "part_number", "change_type", "old_value", "new_value"],
        [["ECN-2026-001", "C-200", "replace", "C-200", "C-250"]],
    )
    parts_csv = _make_csv(
        ["part_number", "description", "lifecycleStatus", "safetyCritical", "approvedSupplier"],
        [
            ["C-200", "Capacitor 10uF", "ACTIVE", "false", "Supplier-B"],
            ["C-250", "Capacitor 10uF Old Version", "OBSOLETE", "false", "Supplier-B"],
        ],
    )
    results = ecn_checker.run_checks({
        "ecn_changes.csv": changes_csv,
        "parts_master.csv": parts_csv,
    })
    changes_result = next(r for r in results if r["file_type"] == "ecn_changes")
    rule_ids = [i["rule"] for i in changes_result["issues"]]
    assert "ECN-C-006" in rule_ids


def test_ecn_c006_active_new_part_passes():
    """ECN-C-006: replacing with an ACTIVE part should not raise ECN-C-006."""
    changes_csv = _make_csv(
        ["ecn_number", "part_number", "change_type", "old_value", "new_value"],
        [["ECN-2026-002", "C-300", "replace", "C-300", "C-350"]],
    )
    parts_csv = _make_csv(
        ["part_number", "description", "lifecycleStatus", "safetyCritical", "approvedSupplier"],
        [
            ["C-300", "Resistor 100 Ohm", "ACTIVE", "false", "Supplier-C"],
            ["C-350", "Resistor 100 Ohm Low-Cost", "ACTIVE", "false", "Supplier-D"],
        ],
    )
    results = ecn_checker.run_checks({
        "ecn_changes.csv": changes_csv,
        "parts_master.csv": parts_csv,
    })
    changes_result = next(r for r in results if r["file_type"] == "ecn_changes")
    rule_ids = [i["rule"] for i in changes_result["issues"]]
    assert "ECN-C-006" not in rule_ids


def test_ecn_c006_part_not_in_master():
    """ECN-C-006: replacing with a part not in parts master should raise an error."""
    changes_csv = _make_csv(
        ["ecn_number", "part_number", "change_type", "old_value", "new_value"],
        [["ECN-2026-003", "C-200", "replace", "C-200", "C-999-UNKNOWN"]],
    )
    parts_csv = _make_csv(
        ["part_number", "description", "lifecycleStatus", "safetyCritical", "approvedSupplier"],
        [["C-200", "Capacitor 10uF", "ACTIVE", "false", "Supplier-B"]],
    )
    results = ecn_checker.run_checks({
        "ecn_changes.csv": changes_csv,
        "parts_master.csv": parts_csv,
    })
    changes_result = next(r for r in results if r["file_type"] == "ecn_changes")
    rule_ids = [i["rule"] for i in changes_result["issues"]]
    assert "ECN-C-006" in rule_ids


def test_ecn_c006_not_fired_without_parts_file():
    """ECN-C-006 should not fire when no parts file is supplied."""
    changes_csv = _make_csv(
        ["ecn_number", "part_number", "change_type", "old_value", "new_value"],
        [["ECN-2026-001", "C-200", "replace", "C-200", "C-250"]],
    )
    results = ecn_checker.run_checks({"ecn_changes.csv": changes_csv})
    changes_result = next(r for r in results if r["file_type"] == "ecn_changes")
    rule_ids = [i["rule"] for i in changes_result["issues"]]
    assert "ECN-C-006" not in rule_ids


def test_python_checker_generates_dashboard(tmp_path):
    output_dir = tmp_path / "out"
    dashboard = ecn_checker.run_checker(ROOT / "data", output_dir)

    ecn_ids = [e["ecnId"] for e in dashboard["ecns"]]
    assert "ECN-2026-001" in ecn_ids
    assert "ECN-2026-002" in ecn_ids
    assert "ECN-2026-003" in ecn_ids

    # ECN-2026-001 has intentional failures — must be a BLOCKER
    ecn_001 = next(e for e in dashboard["ecns"] if e["ecnId"] == "ECN-2026-001")
    assert ecn_001["blockerCount"] > 0
    assert ecn_001["decision"] == "BLOCKER"

    # ECN-2026-002 is fully approved and well-formed — should pass cleanly
    ecn_002 = next(e for e in dashboard["ecns"] if e["ecnId"] == "ECN-2026-002")
    assert ecn_002["decision"] in ("PASS", "WARNING")

    # ECN-2026-003 is missing description and effectiveDate — expect warnings or blockers
    ecn_003 = next(e for e in dashboard["ecns"] if e["ecnId"] == "ECN-2026-003")
    assert ecn_003["warningCount"] > 0 or ecn_003["blockerCount"] > 0

    json_path = output_dir / "ecn-dashboard.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload_ids = [e["ecnId"] for e in payload["ecns"]]
    assert "ECN-2026-001" in payload_ids
    assert "ECN-2026-002" in payload_ids
    assert "ECN-2026-003" in payload_ids
