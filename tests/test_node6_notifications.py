import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from email_notification import send_fail_email, send_pass_email


def _fail_packet():
    return {
        "header": {"ecn_id": "ECN-FAIL-001"},
        "gate": {
            "decision": "FAIL",
            "blockers": [
                {
                    "rule_id": "R01",
                    "severity": "ERROR",
                    "message": "Required field 'description' is missing.",
                }
            ],
            "part_issues": [
                {
                    "flag_type": "MISSING_SUPPLIER",
                    "part_number": "AB-1001",
                    "message": "Part AB-1001 has no approved supplier.",
                }
            ],
            "conflict_alerts": [
                {
                    "flag_type": "HISTORICAL_CONFLICT",
                    "part_number": "AB-1002",
                    "message": "Part AB-1002 conflicts with ECN-2024-010.",
                }
            ],
            "warnings": [],
            "ai_notes": {},
        },
    }


def _pass_packet():
    return {
        "header": {"ecn_id": "ECN-PASS-001"},
        "gate": {
            "decision": "PASS",
            "blockers": [],
            "part_issues": [],
            "conflict_alerts": [],
            "warnings": [
                {
                    "rule_id": "R03",
                    "severity": "WARNING",
                    "message": "Duplicate BOM lines should be reviewed.",
                }
            ],
            "ai_notes": {
                "mismatch_flag": True,
                "flags": [
                    {
                        "type": "MISSING_CONTEXT",
                        "detail": "Add the supplier qualification rationale.",
                    }
                ],
                "recommendation": "Chief Engineer should review the rationale.",
                "confidence": None,
                "ai_available": True,
            },
        },
    }


def test_fail_notification_dry_run_emails_only_engineer(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")

    result = send_fail_email(_fail_packet(), "engineer@example.com")

    assert result["sent"] is False
    assert result["dry_run"] is True
    assert result["recipients"] == ["engineer@example.com"]
    assert result["subject"] == "[ECN-FAIL-001] Action Required — Fix and Resubmit"
    assert "❌ Blockers" in result["body"]
    assert "Required field 'description' is missing." in result["body"]
    assert "❌ Part Issues" in result["body"]
    assert "[MISSING_SUPPLIER] AB-1001" in result["body"]
    assert "Part AB-1001 has no approved supplier." in result["body"]
    assert "❌ Conflicts" in result["body"]
    assert "Part AB-1002 conflicts with ECN-2024-010." in result["body"]
    assert "fix the issues above and resubmit" in result["body"]


def test_pass_notification_dry_run_emails_engineer_and_ce(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")

    result = send_pass_email(
        _pass_packet(), "engineer@example.com", "ce@example.com"
    )

    assert result["sent"] is False
    assert result["dry_run"] is True
    assert result["recipients"] == ["engineer@example.com", "ce@example.com"]
    assert result["subject"] == "[ECN-PASS-001] Gate Passed — Ready for CE Review"
    assert "passed the validation gate" in result["body"]
    assert "⚠️ Warnings (advisory only)" in result["body"]
    assert "Duplicate BOM lines should be reviewed." in result["body"]
    assert "🤖 AI Notes (advisory only)" in result["body"]
    assert "[MISSING_CONTEXT] Add the supplier qualification rationale." in result["body"]
    assert "Chief Engineer should review the rationale." in result["body"]
