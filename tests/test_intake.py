import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from intake import build_ecn_packet, load_csv, load_excel, REQUIRED_ECN_FIELDS


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