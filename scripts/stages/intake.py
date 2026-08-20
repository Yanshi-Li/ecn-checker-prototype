"""
Stage 1: Intake & Extraction
Parses ECN Form and BOM files (CSV, Excel, PDF, Email).
Outputs structured data for the Rule Engine.
"""

import csv
import logging
import os
import re
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Optional heavy deps (graceful degradation) ────────────────────────────────
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

# ── Required ECN Fields ───────────────────────────────────────────────────────
REQUIRED_ECN_FIELDS = [
    "change_notice_number",
    "name_of_change",
    "reason_for_change",
    "description_of_change",
    "products_affected",
    "change_actions",
    "date",
]

# ── PDF Field Aliases ─────────────────────────────────────────────────────────
KEY_ALIASES = {
    # Identification
    "change notice number":     "change_notice_number",
    "name of change":           "name_of_change",
    "project":                  "project",
    "product group":            "product_group",
    "change category":          "change_category",
    "associated a3":            "associated_a3",
    "a3 number":                "a3_number",
    # Change Details
    "reason for change":        "reason_for_change",
    "description of change":    "description_of_change",
    "products affected":        "products_affected",
    "change actions":           "change_actions",
    "implementation date":      "date",
    # Roles
    "checker":                  "checker",
    "reviewer":                 "reviewer",
    "chief engineer":           "chief_engineer",
    "bom coordinator":          "bom_coordinator",
}

# ── Known ECN Field Markers (in order of appearance) ─────────────────────────
_FIELD_MARKERS = [
    "Change Notice Number",
    "Name of Change",
    "Project",
    "Product Group",
    "Change Category",
    "Associated A3",
    "A3 Number",
    "Reason for Change",
    "Description of Change",
    "Products Affected",
    "Change Actions",
    "Implementation Date",
    "Checker",
    "Reviewer",
    "Chief Engineer",
    "BOM Coordinator",
]

# ── Stop Words — prevent value from absorbing table/footer content ────────────
_STOP_MARKERS = [
    "SECTION",
    "Parent No.",
    "Part No.",
    "MBOM",
    "EBOM",
    "This document",
    "Page 1/1",
    "ECN-ERROR",
    "ECN-CLEAN",
    "Fisher & Paykel",
]

# ── Section Headers to Skip ───────────────────────────────────────────────────
_SECTION_HEADERS = {
    "section 1",
    "section 2",
    "section 3",
    "section 4",
    "identification",
    "change details",
    "mbom spreadsheet",
    "ebom spreadsheet",
    "compliance or standards",
    "implementation person",
    "ecn check",
    "ecn reviewers",
    "ecn circulation",
}


# ── PDF Helpers ───────────────────────────────────────────────────────────────
def _normalize_pdf_key(raw_key: str) -> str:
    """
    Normalize a raw PDF key into a clean lowercase string.
    Strips asterisks, parentheses, and extra whitespace.
    e.g. '  * Name of Change  ' -> 'name of change'
    """
    key = raw_key.strip()
    key = re.sub(r"^\*+", "", key)        # remove leading asterisks
    key = re.sub(r"\(.*?\)", "", key)     # remove parentheses e.g. (Handout p.6)
    key = re.sub(r"\s+", " ", key)       # collapse whitespace
    return key.strip().lower()
# ── Stop Zones — skip lines containing these strings ─────────────────────────
_SKIP_ZONES = {
    "validation status",
    "error detail",
    "blocker",
    "section 1",
    "section 2",
    "section 3",
    "section 4",
    "identification",
    "change details",
    "mbom spreadsheet",
    "ebom spreadsheet",
    "parent no.",
    "part no.",
    "this document",
    "page 1/1",
    "ecn-error",
    "ecn-clean",
    "fisher & paykel | enterprise",
    "generated for ecn",
    "handout v1",
}
def _should_skip_line(line: str) -> bool:
    """Return True if line is a header, section label, table row, or footer."""
    lower = line.strip().lower()
    if not lower:
        return True
    if re.match(r"^[─\-=*#|]{3,}$", lower):
        return True
    return any(zone in lower for zone in _SKIP_ZONES)

def _parse_pdf_fields(text: str) -> dict:
    """
    Line-by-line ECN field parser.
    Strategy:
      - Preserves \n from layout=True extraction (do NOT join pages with space).
      - Uses 1+ space gap between label and value (no colon needed).
      - Skips error note, section headers, table rows, and footers.
      - De-duplicates markers (e.g. 'Name of Change' in error note vs real field).
      - Accumulates multi-line values until the next known field marker.
    """
    fields = {}
    lines = text.splitlines()

    # Pre-compute sorted markers (longest first) for regex
    marker_pattern = "|".join(
        re.escape(m) for m in sorted(_FIELD_MARKERS, key=len, reverse=True)
    )

    current_key = None
    current_value_parts = []

    def _flush(key, parts):
        if not key:
            return
        value = " ".join(p.strip() for p in parts if p.strip())
        value = re.sub(r"\s+", " ", value).strip().strip(".,|")
        if value:
            fields[key] = value

    for raw_line in lines:
        line = raw_line.strip()

        # ── Skip blank, decorative, section headers, footers ─────────────────
        if _should_skip_line(line):
            continue

        # ── Try to match a known field marker at start of line ────────────────
        marker_match = re.match(
            rf"^({marker_pattern})\s+(.*)",  # 1+ spaces between label & value
            line,
            re.IGNORECASE,
        )

        if marker_match:
            # Save previous field before starting new one
            _flush(current_key, current_value_parts)
            current_value_parts = []

            raw_key = marker_match.group(1).strip()
            raw_value = marker_match.group(2).strip()

            #  Normalize and alias the key
            normalized_key = _normalize_pdf_key(raw_key)
            current_key = KEY_ALIASES.get(
                normalized_key,
                normalized_key.replace(" ", "_")
            )

            #  Save the value on the same line
            if raw_value:
                current_value_parts.append(raw_value)

        else:
            #  Continuation line — append to current field value
            if current_key and line:
                current_value_parts.append(line)

    #  Flush the very last field
    _flush(current_key, current_value_parts)

    return fields


# ── PDF Loader ────────────────────────────────────────────────────────────────
def load_pdf(filepath: str) -> dict:
    """
    Extract key-value fields from a PDF ECN form (requires pdfplumber).
    Uses layout=True to preserve line breaks and column spacing.
    """
    if not HAS_PDF:
        raise ImportError("pdfplumber is required: pip install pdfplumber")

    raw_text = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            #  layout=True preserves \n between lines — do NOT join with space
            text = page.extract_text(layout=True)
            if text:
                raw_text.append(text)

    #  Join pages with \n — NOT space
    full_text = "\n".join(raw_text)

    result = _parse_pdf_fields(full_text)
    logger.info("PDF loaded: %s (%d fields extracted)", filepath, len(result))
    return result


# ── CSV Loader ────────────────────────────────────────────────────────────────
def load_csv(filepath: str) -> list[dict]:
    """Load a CSV file into a list of row dicts."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip().lower(): v.strip() for k, v in row.items()})
    logger.info("CSV loaded: %s (%d rows)", filepath, len(rows))
    return rows


# ── Excel Helpers ─────────────────────────────────────────────────────────────
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


# ── Excel Loader ──────────────────────────────────────────────────────────────
def load_excel(filepath: str) -> list[dict]:
    """Load an Excel file into a list of row dicts (requires pandas)."""
    if not HAS_PANDAS:
        raise ImportError("pandas is required: pip install pandas openpyxl")

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


# ── Email Helpers ─────────────────────────────────────────────────────────────
def _normalize_email_key(value: str) -> str:
    """Normalize email field names such as 'ECN ID' or 'Affected Assembly'."""
    normalized = re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower())
    return normalized.strip()


def _flatten_email_body(raw_text: str) -> str:
    """Convert HTML content into plain text with a readable line structure."""
    if not raw_text:
        return ""
    cleaned = unescape(raw_text)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"</p>|</div>|</li>|</tr>|</table>", "\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"&nbsp;", " ", cleaned)
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", "\n", cleaned)
    return cleaned.strip()


def _extract_email_body(raw_bytes: bytes) -> str:
    """Return the readable text body from an .eml message."""
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    body_parts = []
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_maintype()
            disposition = part.get_content_disposition()
            if content_type == "text" and disposition != "attachment":
                payload = part.get_payload(decode=True)
                if payload is None:
                    payload = part.get_payload()
                if isinstance(payload, bytes):
                    try:
                        text = payload.decode("utf-8")
                    except UnicodeDecodeError:
                        text = payload.decode("latin-1", errors="ignore")
                else:
                    text = str(payload)
                if text.strip():
                    body_parts.append(
                        _flatten_email_body(text)
                        if part.get_content_subtype() == "html"
                        else text
                    )
    else:
        payload = message.get_payload(decode=True)
        if payload is not None:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                text = payload.decode("latin-1", errors="ignore")
        else:
            text = str(message.get_payload())
        body_parts.append(
            _flatten_email_body(text)
            if message.get_content_subtype() == "html"
            else text
        )

    combined = "\n".join(part for part in body_parts if part).strip()
    if not combined:
        raw = message.get_payload()
        if isinstance(raw, str):
            combined = _flatten_email_body(raw)
    return combined.strip()


def _normalize_email_date(value: str) -> str:
    """Convert RFC 2822 email dates to YYYY-MM-DD when possible."""
    if not value:
        return ""
    cleaned = value.strip().strip("\"'")
    try:
        dt = parsedate_to_datetime(cleaned)
        return dt.strftime("%Y-%m-%d")
    except (TypeError, ValueError, IndexError):
        return cleaned


def _parse_email_header_fields(email_text: str, from_header: str = "") -> dict:
    """Normalize an email body into the same ECN header schema used by the pipeline."""
    text = (email_text or "").strip()
    if not text:
        return {
            "ecn_id":        "",
            "title":         "ECN from email",
            "description":   "",
            "author":        from_header or "email-submitter",
            "date":          "",
            "affected_parts": "",
            "change_type":   "modify",
        }

    normalized_text = re.sub(r"\s+", " ", text)
    labels = [
        ("ecn_id",         r"(?:ECN\s*ID|ECN\s*NUMBER|ECN)"),
        ("title",          r"Title"),
        ("affected_parts", r"Affected\s+assembly|Affected\s+part|Affected\s+parts"),
        ("change_type",    r"Change\s+type|Action|Request\s+type"),
        ("description",    r"Description|Summary|Change\s+summary|Change\s+request"),
        ("date",           r"Date|Effective\s+date|Submitted\s+date|Request\s+date"),
        ("author",         r"Author|Submitted\s+by|Requested\s+by|From"),
    ]
    fields: dict[str, str] = {}

    for idx, (field_name, label_regex) in enumerate(labels):
        next_label = "|".join(rf"(?:{regex})" for _, regex in labels[idx + 1:])
        pattern = rf"(?is)(?:{label_regex})\s*[:\-]?\s*(.*?)(?=(?:{next_label})|$)"
        match = re.search(pattern, normalized_text)
        if match:
            value = match.group(1).strip().strip(" \t\n\r:*#-")
            if value:
                fields[field_name] = value

    if not fields.get("ecn_id"):
        match = re.search(r"(?i)\bECN[-: ]*([A-Z0-9-]+)\b", normalized_text)
        if match:
            fields["ecn_id"] = match.group(1)

    if not fields.get("title"):
        match = re.search(
            r"(?is)Title\s*[:\-]?\s*(.*?)(?=(?:\bAffected\s+assembly\b|\bChange\s+type\b|\bDescription\b|\bDate\b|\bRequested\s+by\b)|$)",
            normalized_text
        )
        if match:
            fields["title"] = match.group(1).strip().strip(" \t\n\r:*#-")

    header = {
        "ecn_id":         fields.get("ecn_id") or "",
        "title":          fields.get("title") or "ECN from email",
        "description":    fields.get("description") or "",
        "author":         fields.get("author") or from_header or "email-submitter",
        "date":           _normalize_email_date(fields.get("date") or ""),
        "affected_parts": fields.get("affected_parts") or "",
        "change_type":    (fields.get("change_type") or "modify").strip().lower(),
    }

    if not header["change_type"]:
        header["change_type"] = "modify"
    if header["ecn_id"] and header["ecn_id"].lower().startswith("id:"):
        header["ecn_id"] = header["ecn_id"].split(":", 1)[1].strip()

    return header


# ── Email Loader ──────────────────────────────────────────────────────────────
def load_email(filepath: str) -> dict:
    """Load an .eml message, extract its body, and normalize to ECN header schema."""
    raw_bytes = Path(filepath).read_bytes()
    email_text = _extract_email_body(raw_bytes)
    from_header = ""
    date_header = ""
    subject_header = ""
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        from_header = msg.get("from", "")
        date_header = msg.get("date", "")
        subject_header = msg.get("subject", "")
    except Exception:
        pass

    header = _parse_email_header_fields(email_text, from_header=from_header)
    if not header.get("date") and date_header:
        header["date"] = _normalize_email_date(date_header)
    if not header.get("title") and subject_header:
        header["title"] = subject_header
    return header


# ── Validation Pre-check ──────────────────────────────────────────────────────
def validate_ecn_header(header: dict) -> dict:
    """
    Check for missing required ECN fields.
    Returns a validation dict with a list of missing fields.
    """
    packet = {"validation": {"missing_fields": []}}
    for field in REQUIRED_ECN_FIELDS:
        if not header.get(field):
            packet["validation"]["missing_fields"].append(field)
    return packet


# ── Auto-detect File Loader ───────────────────────────────────────────────────
def load_file(filepath: str) -> list[dict] | dict:
    """Auto-detect file type and load accordingly."""
    ext = Path(filepath).suffix.lower()
    if ext == ".csv":
        return load_csv(filepath)
    elif ext in (".xlsx", ".xls"):
        return load_excel(filepath)
    elif ext == ".pdf":
        return load_pdf(filepath)
    elif ext == ".eml":
        return load_email(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

# ── Public entry point ────────────────────────────────────────────────────────
def run_intake(ecn_filepath: str, bom_filepath: str) -> dict:
    """
    Main intake entry point called by the orchestrator (run_hybrid.py).
    Returns a fully structured ECN packet.
    """
    # ── Load files ────────────────────────────────────────────────────────────
    ecn_data = load_file(ecn_filepath)
    bom_data = load_file(bom_filepath)

    # ── Normalize ECN header ──────────────────────────────────────────────────
    if isinstance(ecn_data, dict):
        header = ecn_data
        changes = []
    elif isinstance(ecn_data, list):
        header = ecn_data[0] if ecn_data else {}
        changes = ecn_data[1:] if len(ecn_data) > 1 else []
    else:
        header = {}
        changes = []

    # ── Ensure rule_engine required keys always exist ─────────────────────────
    header.setdefault("change_type", "modify")
    header.setdefault("effective_date", header.get("date", ""))
    header.setdefault("ecn_title", header.get("name_of_change", ""))
    header.setdefault("affected_assembly", header.get("products_affected", ""))

    # ── Build packet ──────────────────────────────────────────────────────────
    packet = {
        "header": header,
        "changes": changes,
        "bom": bom_data if isinstance(bom_data, list) else [],
        "validation": {
            "missing_fields":  [],
            "rule_violations": [],
            "ai_flags":        [],
            "context_flags":   [],
        },
        "source_files": {
            "ecn": ecn_filepath,
            "bom": bom_filepath,
        }
    }

    # ── Pre-check for missing required fields ─────────────────────────────────
    for field in REQUIRED_ECN_FIELDS:
        if not packet["header"].get(field):
            packet["validation"]["missing_fields"].append(field)

    logger.info(
        "Intake complete — %d ECN fields, %d BOM rows, %d missing fields",
        len(packet["header"]),
        len(packet["bom"]),
        len(packet["validation"]["missing_fields"]),
    )

    return packet