import importlib.util
from pathlib import Path

from fpdf import FPDF


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
    text_path.write_text(
        "ECN ID: ECN-2026-002\n"
        "Title: Cost Reduction R301 Swap\n"
        "Affected assembly: A-100\n"
        "Quality approval: yes\n"
        "Description: Replace Resistor R301 (C-300) with lower-cost equivalent C-350 to reduce unit cost by 15%. Supplier-D has been qualified and approved.\n"
        "Change 1: Replace component C-300 with C-350 quantity 4\n",
        encoding="utf-8"
    )

    normalized_text = ecn_intake.load_ecn_from_path(text_path)
    assert normalized_text["ecnId"] == "ECN-2026-002"
    assert normalized_text["affectedAssembly"] == "A-100"
    assert len(normalized_text["changes"]) == 1

    pdf_path = tmp_path / "sample_ecn.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 100 >>\nstream\n"
        b"ECN ID: ECN-2026-003\nTitle: Stock Shortage C-200 Concession\nAffected assembly: A-100\nQuality approval: no\n"
        b"Description:\nChange 1: Replace component C-200 with C-260 quantity 1\nChange 2: Replace component C-100 with C-100 quantity 2\nendstream\nendobj\n"
    )

    normalized_pdf = ecn_intake.load_ecn_from_path(pdf_path)
    assert normalized_pdf["ecnId"] == "ECN-2026-003"
    # ECN-2026-003 has a blank description — description should be empty or missing
    assert normalized_pdf.get("description", "").strip() == ""


def test_load_ecn_from_generated_pdf_file(tmp_path):
    pdf_path = tmp_path / "generated_ecn.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(
        0,
        8,
        "ECN ID: ECN-2026-999\n"
        "Title: PDF Extraction Test\n"
        "Affected assembly: A-100\n"
        "Quality approval: no\n"
        "Description: Replace obsolete capacitor with approved alternative.\n"
        "Change 1: Replace component C-200 with C-250 quantity 1",
    )
    pdf.output(str(pdf_path))

    normalized_pdf = ecn_intake.load_ecn_from_path(pdf_path)
    assert normalized_pdf["ecnId"] == "ECN-2026-999"
    assert normalized_pdf["title"] == "PDF Extraction Test"
    assert normalized_pdf["affectedAssembly"] == "A-100"
    assert normalized_pdf["description"] == "Replace obsolete capacitor with approved alternative."
    assert len(normalized_pdf["changes"]) == 1


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
