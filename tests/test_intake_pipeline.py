import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("ecn_intake", "scripts/ecn_intake.py")
ecn_intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecn_intake)


def test_normalize_ecn_text_and_build_input_files(tmp_path):
    raw_text = """ECN Intake from email\nECN ID: ECN-2026-001\nTitle: Sample ECN from email intake\nAffected assembly: A-100\nQuality approval: no\nDescription: Replace the obsolete capacitor with an approved alternative and adjust the affected assembly quantity for the next release.\nChange 1: Replace component C-200 with C-250 quantity 1\nChange 2: Remove component C-999 quantity 1\nChange 3: Add component C-100 quantity 1\n"""

    normalized = ecn_intake.normalize_ecn_text(raw_text)

    assert normalized["ecnId"] == "ECN-2026-001"
    assert normalized["affectedAssembly"] == "A-100"
    assert len(normalized["changes"]) == 3

    output_dir = tmp_path / "intake-data"
    created_dir = ecn_intake.build_input_files(normalized, output_dir, Path("data"))

    assert created_dir == output_dir
    assert (output_dir / "ecn_header.csv").exists()
    assert (output_dir / "ecn_changes.csv").exists()
    assert (output_dir / "parts.csv").exists()
    assert (output_dir / "master_bom.csv").exists()


def test_load_ecn_from_text_and_pdf_files(tmp_path):
    text_path = tmp_path / "sample_ecn.txt"
    text_path.write_text("ECN ID: ECN-2026-002\nTitle: Sample from text file\nAffected assembly: A-100\nQuality approval: yes\nDescription: Replace the obsolete capacitor with an approved alternative.\nChange 1: Add component C-100 quantity 1\n", encoding="utf-8")

    normalized_text = ecn_intake.load_ecn_from_path(text_path)
    assert normalized_text["ecnId"] == "ECN-2026-002"

    pdf_path = tmp_path / "sample_ecn.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 100 >>\nstream\nECN ID: ECN-2026-003\nTitle: Sample from PDF file\nAffected assembly: A-100\nQuality approval: no\nDescription: Replace the obsolete capacitor with an approved alternative.\nChange 1: Add component C-100 quantity 1\nendstream\nendobj\n"
    )

    normalized_pdf = ecn_intake.load_ecn_from_path(pdf_path)
    assert normalized_pdf["ecnId"] == "ECN-2026-003"


def test_load_ecn_from_eml_file(tmp_path):
    eml_path = tmp_path / "sample_ecn.eml"
    eml_path.write_bytes(
        b"Subject: Sample ECN from email\n"
        b"From: coordinator@example.com\n"
        b"To: reviewer@example.com\n"
        b"\n"
        b"ECN ID: ECN-2026-006\n"
        b"Title: Sample from email file\n"
        b"Affected assembly: A-100\n"
        b"Quality approval: no\n"
        b"Description: Replace the obsolete capacitor with an approved alternative.\n"
        b"Change 1: Add component C-100 quantity 1\n"
    )

    normalized_email = ecn_intake.load_ecn_from_path(eml_path)
    assert normalized_email["ecnId"] == "ECN-2026-006"
