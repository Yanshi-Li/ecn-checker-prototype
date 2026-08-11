import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from intake import build_ecn_packet, load_csv, REQUIRED_ECN_FIELDS


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