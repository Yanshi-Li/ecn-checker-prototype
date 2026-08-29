import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from intake import (
    REQUIRED_ECN_FIELDS,
    build_ecn_packet,
    load_excel,
    load_file,
    run_intake,
    validate_ecn_header,
)


DATA_DIR = Path(__file__).parent.parent / "data"
HTML_ECN_PATH = DATA_DIR / "ECN 4078575 DD PH12 Motor Controller - PCB 519123 rev B1 Modules Update.html"
PDF_BOM_PATH = DATA_DIR / "4078575-MBOM_xlsx.pdf"



def test_load_excel_mbom_template(tmp_path):
    path = tmp_path / "MBOM_Mocked.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "MBOM Spreadsheet"
    ws.append(["Help", "BILLS OF MATERIAL CHANGES TEMPLATE", "", "", "", "", "", "", "", "", "",
                "", "", ""])
    ws.append(["PART MASTER CHANGES (Part Details)", "", "", "", "", "", "", "", "", "", "",
                "", "", "", ""])
    ws.append(["Select BOM Database", "Select Action", "Part Number", "Part Description (max. 30 characters)",
               "Part Issue", "Select Unit of Measure", "Select Primary Role", "Part Class",
               "Drawing Number", "Drawing Issue", "Select Part Status", "If required Intro Date",
               "ECN number", "Additional info"])
    ws.append(["MBOM", "ADD", "1001234", "Induction Cooktop Glass Top", "A", "EA", "Primary",
               "Electrical", "DRW-10012", "A", "Active", "2026-08-01", "ECN-4000012",
               "New glass spec applied"])
    ws.append(["MBOM", "DELETE", "1001239", "Legacy Ignition Module", "B", "EA", "Primary",
               "Electrical", "DRW-10017", "B", "Obsolete", "2026-08-03", "ECN-4000014",
               "Replaced by 1001245"])
    wb.save(path)

    rows = load_excel(str(path))
    assert len(rows) == 2
    assert rows[0]["part_number"] == "1001234"
    assert rows[1]["quantity"] == "1"


def _make_header(**kwargs):
    base = {f: "val" for f in REQUIRED_ECN_FIELDS}
    base.update(kwargs)
    return base


def test_packet_structure():
    header = _make_header()
    packet = build_ecn_packet([header], [])
    assert "header" in packet
    assert "bom" in packet
    assert "validation" in packet


def test_missing_fields_detected():
    header = {"ecn_id": "E001"}  # missing most fields
    packet = build_ecn_packet([header], [])
    assert len(packet["validation"]["missing_fields"]) > 0


def test_complete_header_no_missing():
    header = _make_header()
    packet = build_ecn_packet([header], [])
    assert packet["validation"]["missing_fields"] == []


def test_pdf_dict_input():
    header = _make_header()
    packet = build_ecn_packet(header, [])  # dict, not list
    assert packet["header"] == header


def test_load_email_into_header_dict(tmp_path):
    eml_path = tmp_path / "sample_ecn.eml"
    eml_path.write_bytes(
        b"Subject: ECN-2026-007 Sample email update\n"
        b"From: coordinator@example.com\n"
        b"Date: 2026-08-10\n"
        b"\n"
        b"ECN ID: ECN-2026-007\n"
        b"Title: Sample email intake\n"
        b"Affected assembly: A-100\n"
        b"Change type: modify\n"
        b"Description: Replace the obsolete capacitor with an approved alternative and update the documentation.\n"
        b"Requested by: Jane Reviewer\n"
    )

    data = __import__("intake").load_file(str(eml_path))
    assert data["ecn_id"] == "ECN-2026-007"
    assert data["title"] == "Sample email intake"
    assert "obsolete capacitor" in data["description"].lower()
    assert data["change_type"] == "modify"


def test_load_sample_html_ecn_form():
    data = load_file(str(HTML_ECN_PATH), role="ecn")

    assert data["change_notice_number"] == "4078575"
    assert data["name_of_change"] == "DD PH12 Motor Controller - PCB 519123 rev B1 Modules Update"
    for field in (
        "reason_for_change",
        "description_of_change",
        "products_affected",
        "change_actions",
        "date",
    ):
        assert data[field]
    assert validate_ecn_header(data)["validation"]["missing_fields"] == []


def test_load_sample_pdf_bom():
    rows = load_file(str(PDF_BOM_PATH), role="bom")

    assert len(rows) == 4
    assert [row["line_number"] for row in rows] == ["1", "2", "3", "4"]
    assert rows[0] == {
        "part_number": "567953",
        "description": "MOD MC DD RX24T PH12J 230V DBL",
        "quantity": "1",
        "unit": "EA",
        "action": "ADD",
        "source": "Thailand",
        "line_number": "1",
    }


def test_pdf_loading_is_role_aware():
    assert isinstance(load_file(str(PDF_BOM_PATH), role="ecn"), dict)
    assert isinstance(load_file(str(PDF_BOM_PATH), role="bom"), list)


def test_load_file_rejects_unknown_role():
    with pytest.raises(ValueError, match="Unsupported file role"):
        load_file(str(HTML_ECN_PATH), role="review")


def test_run_intake_with_sample_html_ecn_and_pdf_bom():
    packet = run_intake(str(HTML_ECN_PATH), str(PDF_BOM_PATH))

    assert packet["validation"]["missing_fields"] == []
    assert len(packet["bom"]) == 4
    assert packet["source_files"] == {
        "ecn": str(HTML_ECN_PATH),
        "bom": str(PDF_BOM_PATH),
    }


def test_load_html_email_body(tmp_path):

    eml_path = tmp_path / "html_email.eml"
    eml_path.write_bytes(
        b"Content-Type: multipart/alternative; boundary=abc\n"
        b"From: coordinator@example.com\n"
        b"Subject: ECN-2026-008\n"
        b"Date: Tue, 12 Aug 2026 13:00:00 +1200\n"
        b"\n"
        b"--abc\n"
        b"Content-Type: text/html; charset=utf-8\n"
        b"\n"
        b"<html><body><p><strong>ECN ID:</strong> ECN-2026-008</p>"
        b"<p><strong>Title:</strong> HTML Email Intake</p>"
        b"<p><strong>Affected assembly:</strong> A-100</p>"
        b"<p><strong>Change type:</strong> replace</p>"
        b"<p><strong>Description:</strong> Replace the legacy voltage regulator with an approved variant.</p>"
        b"<p><strong>Requested by:</strong> Sam Tester</p></body></html>\n"
        b"--abc--\n"
    )

    data = __import__("intake").load_file(str(eml_path))
    assert data["ecn_id"] == "ECN-2026-008"
    assert data["title"] == "HTML Email Intake"
    assert data["change_type"] == "replace"
    assert data["date"] == "2026-08-12"
    assert "legacy voltage regulator" in data["description"].lower()