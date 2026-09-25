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
from scripts.batch_intake import (
    BatchIntakeError,
    BatchPreparation,
    extract_filename_identifier,
)

from scripts.batch_orchestration import BomInput, LogicalEcnInput, NormalizedBatch







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


def test_reviewer_metric_cards_show_the_evaluation_measures():
    assert streamlit_app.reviewer_metric_cards(
        {"total_attempts": 12, "pass_count": 8, "pass_percentage": 66.7,
         "fail_count": 4, "fail_percentage": 33.3,
         "agreement_percentage": 75.0, "average_duration_seconds": 2.34}
    ) == [("Attempts", "12"), ("PASS", "8 (66.7%)"), ("FAIL", "4 (33.3%)"),
          ("Agreement", "75.0%"), ("Avg check", "2.34 s")]


def test_filtered_attempts_applies_decision_status_and_tester_filters():
    attempts = [
        {"system_decision": "FAIL", "review_status": "READY", "tester_email": "alice@example.com"},
        {"system_decision": "PASS", "review_status": "SUBMITTED", "tester_email": "bob@example.com"},
    ]
    filtered = streamlit_app._filtered_attempts(attempts, "FAIL", "All", "alice")
    assert filtered == [attempts[0]]


def test_finding_rows_stringify_structured_values_for_arrow():
    rows = streamlit_app._finding_rows([
        {"rule_id": "H01", "evidence": {"field": "description"}, "location": {"field": "header"}},
        {"rule_id": "H02", "evidence": "plain text", "location": "bom"},
    ])

    assert rows[0]["Evidence"] == '{"field": "description"}'
    assert rows[0]["Location"] == '{"field": "header"}'
    assert rows[1]["Evidence"] == "plain text"


def test_manual_ecn_csv_uses_canonical_headers_and_escapes_values():

    csv_text = streamlit_app.manual_ecn_csv(_valid_values())
    assert csv_text.splitlines()[0].startswith("change_notice_number,name_of_change")
    assert '"Replace the old capacitor,\nthen update the drawing."' in csv_text
    assert "ecn_number" not in csv_text.splitlines()[0]


def test_streamlit_upload_temp_path_preserves_filename_identifier():
    class FakeUpload:
        name = "ECN-4078575.csv"

        @staticmethod
        def getvalue():
            return b"change_notice_number\n4078575\n"

    temporary_path = Path(streamlit_app._write_upload(FakeUpload()))
    try:
        assert extract_filename_identifier(temporary_path) == "4078575"
        assert temporary_path.name.startswith("ECN-4078575_")
    finally:
        temporary_path.unlink(missing_ok=True)



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


def test_batch_preview_rows_groups_boms_by_filename_identifier():
    preparation = BatchPreparation(
        NormalizedBatch(
            logical_ecns=(
                LogicalEcnInput("4078575", {}, {"source_file": "ECN-4078575.csv"}),
                LogicalEcnInput("4002659", {}, {"source_file": "ECN-4002659.csv"}),
            ),
            bom_inputs=(
                BomInput(
                    "4078575-MBOM.csv",
                    "PRESENT",
                    {},
                    {"source_file": "4078575-MBOM.csv"},
                    suggested_ecn_key="4078575",
                ),
            ),
            mappings={"4078575-MBOM.csv": "4078575"},
            mapping_confirmed=True,
        ),
        (),
    )

    rows = streamlit_app.batch_preview_rows(preparation)

    assert rows == [
        {
            "ECN": "4002659",
            "ECN file": "ECN-4002659.csv",
            "BOM": "—",
            "BOM state": "ABSENT",
            "Status": "Ready (ECN only)",
        },
        {
            "ECN": "4078575",
            "ECN file": "ECN-4078575.csv",
            "BOM": "4078575-MBOM.csv",
            "BOM state": "PRESENT",
            "Status": "Ready",
        },
    ]


def test_persisted_batch_case_records_attempt_and_decision(monkeypatch):
    case = streamlit_app.BatchCase(
        "ECN-1:ECN_ONLY",
        LogicalEcnInput("ECN-1", {}, {"source_file": "ecn.csv"}),
        None,
    )
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(streamlit_app, "_evaluation_db_config", lambda: {"ECN_DB_PASSWORD": "x"})
    monkeypatch.setattr(streamlit_app, "connect_evaluation_db", lambda config: Connection())
    monkeypatch.setattr(streamlit_app, "start_precheck", lambda connection, session, case_id: 10)
    monkeypatch.setattr(streamlit_app, "_execute_batch_case", lambda value: {"decision": "PASS", "packet": _packet("PASS")})
    monkeypatch.setattr(
        streamlit_app,
        "complete_precheck",
        lambda connection, attempt, session, decision, payload: calls.append((attempt, decision, payload)),
    )
    monkeypatch.setattr(
        streamlit_app,
        "update_precheck_case_status",
        lambda connection, case_id, status: calls.append((case_id, status)),
    )

    result = streamlit_app._execute_persisted_batch_case(
        case, {"session_id": 3, "case_ids": {case.case_id: 7}}
    )

    assert result["decision"] == "PASS"
    assert calls[0][0:2] == (10, "PASS")
    assert calls[1] == (7, "PASS")


def test_batch_error_rows_expose_role_file_and_problem():

    preparation = BatchPreparation(
        NormalizedBatch(logical_ecns=(), bom_inputs=()),
        (BatchIntakeError(Path("bad.txt"), "bom", "unsupported bom file format"),),
    )

    assert streamlit_app.batch_error_rows(preparation) == [{
        "Role": "BOM",
        "File": "bad.txt",
        "Problem": "unsupported bom file format",
    }]



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


class _FailingSMTP:
    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        raise RuntimeError("SMTP password should not appear in logs")


def test_send_validation_email_uses_supplied_recipient_without_mutating_packet():
    packet = _packet("PASS")
    result = notification.send_validation_email(
        packet,
        recipient="tester@example.com",
        secrets={
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASS": "secret",
        },
        smtp_factory=_FakeSMTP,
    )

    assert result["sent"] is True
    assert _FakeSMTP.instance.sent[1] == ["tester@example.com"]
    assert "approval" not in packet



def test_send_validation_email_reports_missing_configuration_without_leaking_secret():
    result = notification.send_validation_email(
        _packet(),
        recipient="tester@example.com",
        environ={"SMTP_USER": "sender@example.com"},
    )


    assert result == {"sent": False, "status": "not_configured", "message": "SMTP is not configured."}
    assert "secret" not in result["message"]


def test_send_validation_email_logs_safe_failure_details(caplog):
    result = notification.send_validation_email(
        _packet(),
        recipient="tester@example.com",
        secrets={
            "SMTP_HOST": "smtp.example.com",

            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASS": "secret",
        },
        smtp_factory=_FailingSMTP,
    )

    assert result == {"sent": False, "status": "failed", "message": "Email could not be sent."}
    assert "SMTP delivery failed during starttls (RuntimeError) to smtp.example.com:587" in caplog.text
    assert "SMTP password should not appear in logs" not in caplog.text
    assert "secret" not in caplog.text


