import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("ecn_checker", ROOT / "scripts" / "ecn_checker.py")
ecn_checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecn_checker)


def test_python_checker_generates_dashboard(tmp_path):
    output_dir = tmp_path / "out"
    dashboard = ecn_checker.run_checker(ROOT / "data", output_dir)

    assert dashboard["ecns"][0]["ecnId"] == "ECN-2026-001"
    assert dashboard["ecns"][0]["blockerCount"] > 0
    assert dashboard["ecns"][0]["decision"] == "BLOCKER"

    json_path = output_dir / "ecn-dashboard.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["ecns"][0]["ecnId"] == "ECN-2026-001"
