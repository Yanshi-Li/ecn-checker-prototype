import importlib.util
import json
import tempfile
from pathlib import Path


spec = importlib.util.spec_from_file_location("ai_assistant", "scripts/ai_assistant.py")
ai_assistant = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_assistant)


def test_generate_summary_from_dashboard(tmp_path):
    dashboard = {
        "ecns": [
            {
                "ecnId": "ECN-100",
                "title": "Sample ECN",
                "status": "DRAFT",
                "affectedAssembly": "A-100",
                "effectiveDate": "2026-09-01",
                "qualityApproval": False,
                "passCount": 2,
                "warningCount": 1,
                "blockerCount": 2,
                "decision": "BLOCKER",
                "results": [
                    {"severity": "BLOCKER", "ruleId": "PART-004", "ruleDescription": "Lifecycle check", "message": "Part is obsolete"},
                    {"severity": "BLOCKER", "ruleId": "BOM-003", "ruleDescription": "Quantity check", "message": "Quantity was zero"},
                    {"severity": "WARNING", "ruleId": "REG-001", "ruleDescription": "Quality approval", "message": "Quality approval missing"},
                ],
            }
        ]
    }

    output_path = tmp_path / "ai-summary.json"
    html_path = tmp_path / "hybrid-dashboard.html"

    ai_assistant.generate_assistant_output(dashboard, output_path, html_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["ecns"][0]["riskLevel"] == "high"
    assert "review" in payload["ecns"][0]["summary"].lower()
    assert len(payload["ecns"][0]["reviewerActions"]) >= 2
    assert html_path.exists()
