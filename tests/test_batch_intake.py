"""Tests for building batch inputs from raw ECN and BOM paths."""

from pathlib import Path

from scripts.batch_intake import build_batch_from_paths, extract_filename_identifier


def _ecn(path: Path, number: str) -> None:
    path.write_text(
        "change_notice_number,name_of_change,reason_for_change,description_of_change\n"
        f"{number},Change,Reason,Description\n",
        encoding="utf-8",
    )


def _bom(path: Path, rows: str = "part_number,quantity,action\nP-1,1,ADD\n") -> None:
    path.write_text(rows, encoding="utf-8")


def test_extracts_exact_seven_digit_identifier_from_filename():
    assert extract_filename_identifier("ECN 4078575 change.html") == "4078575"
    assert extract_filename_identifier("ECN-12345678.csv") is None
    assert extract_filename_identifier("unknown.csv") is None


def test_builds_folder_batch_and_matches_boms_by_filename_identifier(tmp_path):
    ecn_dir = tmp_path / "ecns"
    bom_dir = tmp_path / "boms"
    ecn_dir.mkdir()
    bom_dir.mkdir()
    _ecn(ecn_dir / "ECN-4078575.csv", "4078575")
    _ecn(ecn_dir / "ECN-4002659.csv", "4002659")
    _bom(bom_dir / "4078575-MBOM.csv")
    _bom(bom_dir / "4078575-EBOM.csv")
    _bom(bom_dir / "4002659-MBOM.csv")

    prepared = build_batch_from_paths([ecn_dir], [bom_dir])

    assert prepared.errors == ()
    assert [ecn.key for ecn in prepared.batch.logical_ecns] == ["4002659", "4078575"]
    assert {bom.suggested_ecn_key for bom in prepared.batch.bom_inputs} == {"4002659", "4078575"}
    assert len(prepared.batch.bom_inputs) == 3
    assert prepared.batch.mapping_confirmed is True


def test_preserves_empty_bom_and_reports_unmatched_or_invalid_files(tmp_path):
    ecn = tmp_path / "ECN-4078575.csv"
    _ecn(ecn, "4078575")
    empty_bom = tmp_path / "4078575-MBOM.csv"
    _bom(empty_bom, "part_number,quantity,action\n")
    unmatched = tmp_path / "9999999-MBOM.csv"
    _bom(unmatched)
    invalid = tmp_path / "notes.txt"
    invalid.write_text("not an input", encoding="utf-8")

    prepared = build_batch_from_paths([ecn], [empty_bom, unmatched, invalid])

    assert prepared.errors
    assert any("9999999" in error.message for error in prepared.errors)
    assert any(error.path == invalid for error in prepared.errors)
    assert prepared.batch.bom_inputs[0].state == "EMPTY"
    assert prepared.batch.bom_inputs[0].suggested_ecn_key == "4078575"


def test_reports_multiple_identifiers_in_one_filename(tmp_path):
    ecn = tmp_path / "ECN-1234567-and-7654321.csv"
    _ecn(ecn, "1234567")

    prepared = build_batch_from_paths([ecn], [])

    assert len(prepared.errors) == 1
    assert "multiple" in prepared.errors[0].message
