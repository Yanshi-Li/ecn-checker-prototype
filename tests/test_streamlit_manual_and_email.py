import csv
import importlib.util
import io
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("streamlit_app_under_test", ROOT / "streamlit_app.py")
streamlit_app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = streamlit_app
spec.loader.exec_module(streamlit_app)

notification = streamlit_app.validation_notification_mod


def _valid_values():
    return {
        "change_notice_number": "ECN-2026-001",
        "name_of_change": "Replace capacitor",
        "reason_for_change": "Improve reliability",
        "description_of_change": "Replace the old capacitor,\nthen update the drawing.",
        "products_affected": "A-100",
        "change_actions": "Replace component",
        "date": "2026-08-14",
    }


def _packet(decision="FAIL"):
    return {
        "header": {
            "change_notice_number": "ECN-2026-001",
            "name_of_change": "Replace capacitor",
            "date": "2026-08-14",
            "products_affected": "A-100",
        },
        "gate": {
            "decision": decision,
            "blockers": [{
                "rule_id": "H01", "severity": "ERROR", "gate_effect": "FAIL",
                "message": "Missing field", "location": "header", "evidence": "reason",
            }] if decision == "FAIL" else [],
            "part_issues": [],
            "conflict_alerts": [],
            "warnings": [{"rule_id": "W01", "severity": "WARNING", "message": "Review wording"}],
            "ai_notes": {"recommendation": "Review the change before submission."},
        },
    }


def test_manual_ecn_csv_uses_canonical_headers_and_escapes_values():
    csv_text = streamlit_app.manual_ecn_csv(_valid_values())
    assert csv_text.splitlines()[0].startswith("change_notice_number,name_of_change")
    assert '"Replace the old capacitor,\nthen update the drawing."' in csv_text
    assert "ecn_number" not in csv_text.splitlines()[0]


def test_manual_bom_csv_generates_line_numbers_and_defaults():
    csv_text = streamlit_app.manual_bom_csv([{"part_number": "P-1"}, {"part_number": "P-2", "quantity": "2.5"}])
    assert "line_number,part_number,description,quantity,unit,action,parent_part_no" in csv_text
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert rows[0]["line_number"] == "1"
    assert rows[0]["part_number"] == "P-1"
    assert rows[0]["quantity"] == "1"
    assert rows[0]["unit"] == "EA"
    assert rows[1]["line_number"] == "2"
    assert rows[1]["quantity"] == "2.5"


def test_validate_manual_input_reports_required_fields_and_bom_errors():
    errors = streamlit_app.validate_manual_input({}, [{"part_number": "", "quantity": "0"}])
    assert any("Change Notice Number is required" in error for error in errors)
    assert "BOM row 1 requires a part number." in errors
    assert "BOM row 1 quantity must be a positive number." in errors


def test_validation_email_contains_gate_and_finding_details():
    subject, body = notification.build_validation_email(_packet())
    assert subject == "ECN Validation Report — ECN-2026-001 — FAIL"
    assert "This is an automated validation report. It is not an approval or rejection decision." in body
    assert "[H01] ERROR Missing field" in body
    assert "Gate Effect: FAIL" in body
    assert "AI Recommendation:" in body


class _FakeSMTP:
    instance = None

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sent = None
        _FakeSMTP.instance = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        self.username = username
        self.password = password

    def sendmail(self, sender, recipients, message):
        self.sent = (sender, recipients, message)


def test_send_validation_email_uses_fixed_recipient_without_mutating_packet():
    packet = _packet("PASS")
    result = notification.send_validation_email(
        packet,
        secrets={"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "sender@example.com", "SMTP_PASS": "secret"},
        smtp_factory=_FakeSMTP,
    )
    assert result["sent"] is True
    assert _FakeSMTP.instance.sent[1] == ["yanshili645@gmail.com"]
    assert "approval" not in packet


def test_send_validation_email_reports_missing_configuration_without_leaking_secret():
    result = notification.send_validation_email(_packet(), environ={"SMTP_USER": "sender@example.com"})
    assert result == {"sent": False, "status": "not_configured", "message": "SMTP is not configured."}
    assert "secret" not in result["message"]
