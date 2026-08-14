"""
Stage 1: Intake & Extraction
Parses ECN Form and BOM files (CSV, Excel, PDF).
Outputs structured data for the Rule Engine.
"""


import csv
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Optional heavy deps (graceful degradation) ──────────────────────────────
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


# ── Field definitions ────────────────────────────────────────────────────────
REQUIRED_ECN_FIELDS = [
    "ecn_id", "title", "description", "author",
    "date", "affected_parts", "change_type"
]

REQUIRED_BOM_FIELDS = [
    "part_number", "description", "quantity", "unit", "line_number"
]


# ── Loaders ──────────────────────────────────────────────────────────────────
def load_csv(filepath: str) -> list[dict]:
    """Load a CSV file into a list of row dicts."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip().lower(): v.strip() for k, v in row.items()})
    logger.info("CSV loaded: %s (%d rows)", filepath, len(rows))
    return rows


def _normalize_excel_key(value: str) -> str:
    """Collapse header names into a stable, lowercase key."""
    if value is None:
        return ""
    cleaned = str(value).strip().lower()
    cleaned = cleaned.replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return cleaned.strip()


def _lookup_value(mapping: dict, *candidates: str) -> str:
    """Return the first mapped value whose normalized key matches a candidate."""
    for candidate in candidates:
        for key, value in mapping.items():
            if key == candidate or key.startswith(candidate) or key.endswith(candidate):
                return value
    return ""


def _coerce_mbom_rows(rows: list[dict]) -> list[dict]:
    """Normalize the MBOM spreadsheet template into the project BOM schema."""
    parsed_rows = []
    for idx, row in enumerate(rows, start=1):
        if not row:
            continue
        normalized = {
            _normalize_excel_key(k): ("" if v is None else str(v).strip())
            for k, v in row.items()
        }

        part_number = _lookup_value(
            normalized,
            "part number",
            "component part number",
            "existing child part number",
            "new child part number",
        )
        if not part_number:
            continue

        quantity = _lookup_value(normalized, "qty", "quantity") or "1"
        unit = _lookup_value(normalized, "select unit of measure") or "EA"
        description = _lookup_value(
            normalized,
            "part description",
            "description",
            "new child part description",
        )

        parsed_rows.append({
            "line_number": str(idx),
            "part_number": part_number,
            "description": description,
            "quantity": quantity,
            "unit": unit,
            "action": _lookup_value(normalized, "select action", "action"),
            "source": _lookup_value(normalized, "select bom database"),
        })

    return parsed_rows


def load_excel(filepath: str) -> list[dict]:
    """Load an Excel file into a list of row dicts (requires pandas)."""
    if not HAS_PANDAS:
        raise ImportError("pandas is required for Excel support: pip install pandas openpyxl")

    df = pd.read_excel(filepath, header=None, dtype=str).fillna("")
    grid = df.values.tolist()
    header_index = None
    header = []
    for idx, row in enumerate(grid):
        normalized = [_normalize_excel_key(str(cell)) for cell in row]
        if any(
            "part number" in cell
            or "select action" in cell
            or "select bom database" in cell
            for cell in normalized
        ):
            header_index = idx
            header = [str(cell).strip() for cell in row]
            break

    if header_index is not None:
        rows = []
        for row in grid[header_index + 1:]:
            if not any(str(cell).strip() for cell in row):
                continue
            item = {}
            for j, name in enumerate(header):
                if j < len(row):
                    item[name] = str(row[j]).strip()
            rows.append(item)
    else:
        df.columns = [str(c).strip().lower() for c in df.columns]
        rows = df.to_dict(orient="records")

    if rows and any(
        "part number" in _normalize_excel_key(str(k))
        or "select action" in _normalize_excel_key(str(k))
        for row in rows for k in row.keys()
    ):
        rows = _coerce_mbom_rows(rows)

    logger.info("Excel loaded: %s (%d rows)", filepath, len(rows))
    return rows


def load_pdf(filepath: str) -> dict:
    """
    Extract key-value text from a PDF ECN form (requires pdfplumber).
    Returns a flat dict of field -> value parsed from the PDF text.
    """
    if not HAS_PDF:
        raise ImportError("pdfplumber is required for PDF support: pip install pdfplumber")

    raw_text = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                raw_text.append(text)

    full_text = "\n".join(raw_text)
    result = _parse_pdf_fields(full_text)
    logger.info("PDF loaded: %s (%d fields extracted)", filepath, len(result))
    return result


def _parse_pdf_fields(text: str) -> dict:
    """
    Naive line-by-line key:value parser for PDF text.
    Extend with regex patterns to match your specific ECN form layout.
    """
    fields = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().lower().replace(" ", "_")] = value.strip()
    return fields


# ── Dispatching loader ───────────────────────────────────────────────────────
def load_file(filepath: str) -> list[dict] | dict:
    """Auto-detect file type and load accordingly."""
    ext = Path(filepath).suffix.lower()
    if ext == ".csv":
        return load_csv(filepath)
    elif ext in (".xlsx", ".xls"):
        return load_excel(filepath)
    elif ext == ".pdf":
        return load_pdf(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


# ── Structured packet builder ────────────────────────────────────────────────
def build_ecn_packet(ecn_data: list[dict] | dict, bom_data: list[dict]) -> dict:
    """
    Combine ECN header data and BOM rows into a single structured packet
    that flows through the rest of the pipeline.
    """
    # Normalize ECN header — support both a single dict (PDF) or
    # a list-of-one-row (CSV/Excel)
    if isinstance(ecn_data, list):
        header = ecn_data[0] if ecn_data else {}
        changes = ecn_data[1:] if len(ecn_data) > 1 else []
    else:
        header = ecn_data
        changes = []

    packet = {
        "header": header,
        "changes": changes,
        "bom": bom_data,
        "validation": {
            "missing_fields": [],
            "rule_violations": [],
            "ai_flags": [],
            "context_flags": [],
        },
    }

    # Pre-check for missing required header fields
    for field in REQUIRED_ECN_FIELDS:
        if not header.get(field):
            packet["validation"]["missing_fields"].append(field)

    # Pre-check for missing required BOM fields
    for row in bom_data:
        for field in REQUIRED_BOM_FIELDS:
            if not row.get(field):
                packet["validation"]["missing_fields"].append(
                    f"bom.{field} (row {row.get('line_number', '?')})"
                )

    logger.info(
        "ECN packet built — ECN ID: %s | BOM rows: %d | Missing fields: %d",
        header.get("ecn_id", "UNKNOWN"),
        len(bom_data),
        len(packet["validation"]["missing_fields"]),
    )
    return packet


# ── Public entry point ───────────────────────────────────────────────────────
def run_intake(ecn_filepath: str, bom_filepath: str) -> dict:
    """
    Main intake entry point called by the orchestrator.
    Returns a fully structured ECN packet.
    """
    ecn_data = load_file(ecn_filepath)
    bom_data = load_file(bom_filepath)

    # PDF returns a single dict; wrap for uniform handling
    if isinstance(bom_data, dict):
        bom_data = [bom_data]

    return build_ecn_packet(ecn_data, bom_data)