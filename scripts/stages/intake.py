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
from html.parser import HTMLParser
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
# Only these ECN form headers are validated by R01.
REQUIRED_ECN_FIELDS = [
    "description_of_change",
    "name_of_change",
    "change_notice_number",
    "reason_for_change",
]

# ── PDF Field Aliases ─────────────────────────────────────────────────────────
KEY_ALIASES = {
    # Identification
    "change notice number":     "change_notice_number",
    "engineering change number": "change_notice_number",
    "number":                   "change_notice_number",
    "name of change":           "name_of_change",
    "name":                     "name_of_change",
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
    "cost impact":              "cost_impact",
    "implementation date":      "date",
    # Roles
    "checker":                  "checker",
    "reviewer":                 "reviewer",
    "chief engineer":           "chief_engineer",
    "bom coordinator":          "bom_coordinator",
}

# ── Known ECN Field Markers (in order of appearance) ─────────────────────────
_FIELD_MARKERS = [
    "Engineering Change Number",
    "Change Notice Number",
    "Number",
    "Name of Change",
    "Name",
    "Project",
    "Product Group",
    "Change Category",
    "Associated A3",
    "A3 Number",
    "Reason for Change",
    "Description of Change",
    "Products Affected",
    "Change Actions",
    "Cost Impact",
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
    "enterprise change handout",      
    "enterprise change notice",       
}
def _should_skip_line(line: str) -> bool:
    """Return True if line is a header, section label, table row, or footer."""
    lower = line.strip().lower()
    if not lower:
        return True
    if re.match(r"^[─\-=*#|]{3,}$", lower):
        return True
    return any(zone in lower for zone in _SKIP_ZONES)
    # Skip MBOM table data rows (start with part/assembly number pattern)
    # e.g. 'ASM-451-TOP Induction Top Assembly Replace...'
    # e.g. 'HE-2045 Heating Element Pro 01 ELECMAN...'
    if re.match(r"^[A-Z]{2,}[-_][A-Z0-9]", line.strip()):
        return True

    return False
    # ── Sentinel values that mean "empty" in the PDF ─────────────────────────────
_EMPTY_SENTINELS = {
    "*** missing / error ***",
    "*** missing ***",
    "*** error ***",
    "n/a",
    "none",
    "-",
    "--",
    "tbd",
    "tbc",
}

def _is_empty_value(value: str) -> bool:
    """Return True if the value is a sentinel placeholder meaning empty."""
    return value.strip().lower() in _EMPTY_SENTINELS

def _parse_pdf_fields(text: str) -> dict:
    """
    Line-by-line ECN field parser.
    Strategy:
      - Preserves \\n from layout=True extraction.
      - Uses 1+ space gap between label and value (no colon needed).
      - Skips error note, section headers, table rows, and footers.
      - Accumulates multi-line values only for known multi-line fields.
      - Para N: lines are always routed to description_of_change, stripped of prefix.
    """
    _SINGLE_LINE_FIELDS = {
        "change_notice_number",
        "name_of_change",
        "project",
        "product_group",
        "change_category",
        "associated_a3",
        "a3_number",
        "products_affected",
        "change_actions",
        "cost_impact",
        "date",
        "checker",
        "reviewer",
        "chief_engineer",
        "bom_coordinator",
    }

    fields = {}
    lines = text.splitlines()

    marker_pattern = "|".join(
        re.escape(m) for m in sorted(_FIELD_MARKERS, key=len, reverse=True)
    )

    current_key = None
    current_value_parts = []
    #  Separate bucket for description paragraphs collected anywhere
    description_parts = []

    def _strip_para_prefix(line: str) -> str:
        """Remove 'Para N:' prefix and return clean value."""
        return re.sub(r"^Para\s+\d+\s*:\s*", "", line, flags=re.IGNORECASE).strip()

    def _flush(key, parts):
        if not key:
            return
        value = " ".join(p.strip() for p in parts if p.strip())
        value = re.sub(r"\s+", " ", value).strip().strip(".,|")
        # Store empty string for sentinel values — key still appears in output
        if _is_empty_value(value):
            fields[key] = ""
        elif value:
            fields[key] = value

    for raw_line in lines:
        line = raw_line.strip()

        if _should_skip_line(line):
            continue

        # ── Detect Para N: lines — always goes to description_of_change ───────
        if re.match(r"^Para\s+\d+\s*:", line, re.IGNORECASE):
            description_parts.append(_strip_para_prefix(line))
            continue

        # ── Try to match a known field marker ─────────────────────────────────
        marker_match = re.match(
            rf"^({marker_pattern})\s+(.*)",
            line,
            re.IGNORECASE,
        )

        if marker_match:
            #  Flush previous field
            _flush(current_key, current_value_parts)
            current_value_parts = []

            raw_key = marker_match.group(1).strip()
            raw_value = marker_match.group(2).strip()

            normalized_key = _normalize_pdf_key(raw_key)
            current_key = KEY_ALIASES.get(
                normalized_key,
                normalized_key.replace(" ", "_")
            )

            #  If value on same line starts with Para N: send to description
            if re.match(r"^Para\s+\d+\s*:", raw_value, re.IGNORECASE):
                description_parts.append(_strip_para_prefix(raw_value))
            elif raw_value:
                current_value_parts.append(raw_value)

        else:
            #  Continuation — only for multi-line fields
            if current_key and line and current_key not in _SINGLE_LINE_FIELDS:
                current_value_parts.append(line)

    #  Flush the last field
    _flush(current_key, current_value_parts)

    #  Merge all description paragraphs into description_of_change
    if description_parts:
        existing = fields.get("description_of_change", "")
        merged = " ".join(description_parts)
        fields["description_of_change"] = (
            (existing + " " + merged).strip() if existing else merged
        )

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
    """Return the first non-empty value whose normalized key matches a candidate."""
    for candidate in candidates:
        for key, value in mapping.items():
            if (
                key == candidate or key.startswith(candidate) or key.endswith(candidate)
            ) and value:
                return value
    return ""


def _normalize_mbom_row(row: dict) -> dict | None:
    """Normalize one MBOM row using the common Excel/PDF column aliases."""
    normalized = {
        _normalize_excel_key(k): ("" if v is None else str(v).strip())
        for k, v in row.items()
    }
    part_number = _lookup_value(
        normalized,
        "existing child part number",
        "new child part number",
        "component part number",
        "part number",
    )
    if not part_number:
        return None

    return {
        "part_number": part_number,
        "description": _lookup_value(
            normalized,
            "existing child part description",
            "new child part description",
            "part description",
            "description",
        ),
        "parent_part_no": _lookup_value(normalized, "parent part number"),
        "parent_part_description": _lookup_value(
            normalized, "parent part description"
        ),
        "quantity": _lookup_value(normalized, "qty", "quantity") or "1",
        "unit": _lookup_value(normalized, "select unit of measure") or "EA",
        "action": _lookup_value(normalized, "select action", "action"),
        "source": _lookup_value(normalized, "select bom database"),
    }


def _combine_mbom_headers(parent_row: list[str], child_row: list[str]) -> list[str]:
    """Combine a grouped MBOM header row with its Number/Description subheaders."""
    headers = []
    current_group = ""
    for parent, child in zip(parent_row, child_row):
        parent_label = str(parent).strip()
        child_label = str(child).strip()
        if parent_label:
            current_group = parent_label
        headers.append(
            f"{current_group} {child_label}".strip()
            if child_label in {"Number", "Description"} and current_group
            else parent_label or child_label
        )
    return headers


def _coerce_mbom_rows(rows: list[dict]) -> list[dict]:
    """Normalize the MBOM spreadsheet template into the project BOM schema."""
    parsed_rows = []
    for row in rows:
        if not row:
            continue
        parsed = _normalize_mbom_row(row)
        if parsed:
            parsed["line_number"] = str(len(parsed_rows) + 1)
            parsed_rows.append(parsed)
    return parsed_rows



# ── Excel Loader ──────────────────────────────────────────────────────────────
def _extract_excel_ecn_header(grid: list[list[str]]) -> dict:
    """Extract a label/value ECN form header from worksheet rows."""
    for row_index, row in enumerate(grid):
        recognized_columns = [
            column_index
            for column_index, cell in enumerate(row)
            if _normalize_excel_key(cell) in KEY_ALIASES
        ]
        if len(recognized_columns) < 2:
            continue

        header = {}
        for column_index in recognized_columns:
            label = _normalize_excel_key(row[column_index])
            canonical_key = KEY_ALIASES[label]
            value = ""
            for value_row in grid[row_index + 1:]:
                if column_index < len(value_row) and str(value_row[column_index]).strip():
                    value = str(value_row[column_index]).strip()
                    break
            header[canonical_key] = value
        return header
    return {}


def load_excel(filepath: str, role: str = "bom") -> list[dict] | dict:
    """Load an Excel ECN form or MBOM worksheet (requires pandas)."""
    if not HAS_PANDAS:
        raise ImportError("pandas is required: pip install pandas openpyxl")

        
    df = pd.read_excel(filepath, header=None, dtype=str).fillna("")
    grid = df.values.tolist()
    if role == "ecn":
        header = _extract_excel_ecn_header(grid)
        if header:
            logger.info("Excel ECN loaded: %s (%d fields extracted)", filepath, len(header))
            return header

    header_index = None
    header = []
    for idx, row in enumerate(grid):
        normalized = [_normalize_excel_key(str(cell)) for cell in row]
        is_part_master_header = any(
            "part number" in cell or "select action" in cell
            for cell in normalized
        )
        is_structure_header = (
            "parent part" in normalized
            and (
                "existing child part" in normalized
                or "new child part" in normalized
            )
        )
        if is_structure_header and idx + 1 < len(grid):
            header_index = idx + 1
            header = _combine_mbom_headers(row, grid[idx + 1])
            break
        if is_part_master_header and header_index is None:
            header_index = idx
            header = [str(cell).strip() for cell in row]

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


def _is_mbom_header(row: list[str | None]) -> bool:
    """Return whether a PDF table row is an MBOM column-header row."""
    headers = [_normalize_excel_key(cell) for cell in row]
    return any("part number" in header for header in headers) and any(
        "action" in header for header in headers
    )


def load_pdf_bom(filepath: str) -> list[dict]:
    """Extract and normalize MBOM tables from a PDF (requires pdfplumber)."""
    if not HAS_PDF:
        raise ImportError("pdfplumber is required: pip install pdfplumber")

    parsed_rows = []
    header = None
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if _is_mbom_header(row):
                        header = row
                        continue
                    row_keys = [_normalize_excel_key(cell) for cell in row]
                    if (
                        "select bom database" in row_keys
                        and any("action" in key for key in row_keys)
                    ):
                        header = None
                        continue
                    if header is None or not any(cell for cell in row):
                        continue

                    raw_row = {
                        str(column): value
                        for column, value in zip(header, row)
                        if column is not None
                    }
                    parsed = _normalize_mbom_row(raw_row)
                    if parsed:
                        parsed["line_number"] = str(len(parsed_rows) + 1)
                        parsed_rows.append(parsed)

    logger.info("PDF BOM loaded: %s (%d rows)", filepath, len(parsed_rows))
    return parsed_rows



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


class _HTMLTableParser(HTMLParser):
    """Collect text cells from HTML table rows without an external dependency."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None and self._row is not None:
            self._row.append("".join(self._cell_parts))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _parse_html_table_fields(raw_html: str) -> dict:
    """Extract label/value ECN fields from the Windchill HTML table layout."""
    parser = _HTMLTableParser()
    parser.feed(raw_html)
    parser.close()

    html_aliases = {
        "created on": "date",
    }
    fields = {}
    pending_key = None

    for row in parser.rows:
        cells = [_flatten_email_body(cell) for cell in row]
        if not cells:
            continue

        label = _normalize_pdf_key(cells[0].rstrip(":"))
        key = KEY_ALIASES.get(label) or html_aliases.get(label)
        if key:
            if len(cells) > 1:
                value = " ".join(cell for cell in cells[1:] if cell).strip()
                if value:
                    fields[key] = value
                pending_key = None
            else:
                pending_key = key
        elif pending_key and cells[0]:
            fields[pending_key] = cells[0]
            pending_key = None

    return fields


def load_html(filepath: str) -> dict:
    """Load an HTML ECN form into the standard PDF-form ECN header schema."""
    raw_html = Path(filepath).read_text(encoding="utf-8", errors="replace")
    fields = _parse_pdf_fields(_flatten_email_body(raw_html))
    fields.update(_parse_html_table_fields(raw_html))
    logger.info("HTML ECN loaded: %s (%d fields extracted)", filepath, len(fields))
    return fields


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
            "change_notice_number": "",
            "title": "ECN from email",
            "description": "",
            "author": from_header or "email-submitter",
            "date": "",
            "affected_parts": "",
            "change_type": "modify",
        }

    normalized_text = re.sub(r"\s+", " ", text)
    labels = [
        ("change_notice_number", r"Change\s+Notice\s+Number"),
        ("title", r"Title"),
        ("affected_parts", r"Affected\s+assembly|Affected\s+part|Affected\s+parts"),
        ("change_type", r"Change\s+type|Action|Request\s+type"),
        ("description", r"Description|Summary|Change\s+summary|Change\s+request"),
        ("date", r"Date|Effective\s+date|Submitted\s+date|Request\s+date"),
        ("author", r"Author|Submitted\s+by|Requested\s+by|From"),
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

    header = {
        "change_notice_number": fields.get("change_notice_number") or "",
        "title": fields.get("title") or "ECN from email",
        "description": fields.get("description") or "",
        "author": fields.get("author") or from_header or "email-submitter",
        "date": _normalize_email_date(fields.get("date") or ""),
        "affected_parts": fields.get("affected_parts") or "",
        "change_type": (fields.get("change_type") or "modify").strip().lower(),
    }

    if not header["change_type"]:
        header["change_type"] = "modify"

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
    normalized_header = _normalize_ecn_header(header)
    packet = {"validation": {"missing_fields": []}}
    for field in REQUIRED_ECN_FIELDS:
        if not normalized_header.get(field):
            packet["validation"]["missing_fields"].append(field)
    return packet


# ── Auto-detect File Loader ───────────────────────────────────────────────────
def load_file(filepath: str, role: str = "ecn") -> list[dict] | dict:
    """Auto-detect file type and load it for the supplied ECN or BOM role."""
    if role not in {"ecn", "bom"}:
        raise ValueError(f"Unsupported file role: {role}")

    ext = Path(filepath).suffix.lower()
    if ext == ".csv":
        return load_csv(filepath)
    if ext in (".xlsx", ".xls"):
        return load_excel(filepath, role=role)
    if ext == ".pdf":
        return load_pdf_bom(filepath) if role == "bom" else load_pdf(filepath)
    if ext in (".html", ".htm") and role == "ecn":
        return load_html(filepath)
    if ext == ".eml":
        return load_email(filepath)
    raise ValueError(f"Unsupported file type: {ext}")



# ── Packet builder ────────────────────────────────────────────────────────────
def _normalize_ecn_header(header: dict) -> dict:
    """Map supported ECN form labels to the canonical validation keys."""
    normalized = {}
    for key, value in header.items():
        label = _normalize_excel_key(key)
        canonical_key = KEY_ALIASES.get(label, key)
        normalized[canonical_key] = "" if value is None else str(value).strip()
    return normalized


def build_ecn_packet(ecn_data, bom_data, source_files=None) -> dict:
    """Build a normalized ECN packet from loaded ECN and BOM data."""
    if isinstance(ecn_data, dict):
        header = _normalize_ecn_header(ecn_data)
        changes = []
    elif isinstance(ecn_data, list):
        header = _normalize_ecn_header(ecn_data[0]) if ecn_data else {}
        changes = ecn_data[1:] if len(ecn_data) > 1 else []
    else:
        header = {}
        changes = []

    header.setdefault("change_type", "modify")

    # ── Build packet ──────────────────────────────────────────────────────────

    packet = {
        "header": header,
        "changes": changes,
        "bom": bom_data if isinstance(bom_data, list) else [],
        "validation": {
            "missing_fields":  [],
            "rule_violations": [],
            "ai_flags":        {},
            "context_flags":   [],
        },
        "source_files": source_files or {},
    }

    # ── Pre-check for missing required fields ─────────────────────────────────
    for field in REQUIRED_ECN_FIELDS:
        if not packet["header"].get(field):
            packet["validation"]["missing_fields"].append(field)

    return packet


# ── Public entry point ────────────────────────────────────────────────────────
def run_intake(ecn_filepath: str, bom_filepath: str) -> dict:
    """
    Main intake entry point called by the orchestrator (run_hybrid.py).
        Returns a fully structured ECN packet.
    """

    ecn_data = load_file(ecn_filepath, role="ecn")
    bom_data = load_file(bom_filepath, role="bom")


    packet = build_ecn_packet(
        ecn_data,
        bom_data,
        source_files={"ecn": ecn_filepath, "bom": bom_filepath},
    )

    logger.info(
        "Intake complete — %d ECN fields, %d BOM rows, %d missing fields",
        len(packet["header"]),
        len(packet["bom"]),
        len(packet["validation"]["missing_fields"]),
    )

    return packet