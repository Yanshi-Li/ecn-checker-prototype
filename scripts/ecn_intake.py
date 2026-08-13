import csv
import importlib.util
import imaplib
import os
import re
import zlib
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Dict, List


def normalize_ecn_text(raw_text: str) -> Dict[str, Any]:
    text = (raw_text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    ecn_id = ""
    title = ""
    affected_assembly = ""
    quality_approval = False
    description = ""
    changes: List[Dict[str, Any]] = []

    for line in lines:
        if line.lower().startswith("ecn id:"):
            ecn_id = line.split(":", 1)[1].strip()
        elif line.lower().startswith("title:"):
            title = line.split(":", 1)[1].strip()
        elif line.lower().startswith("affected assembly:"):
            affected_assembly = line.split(":", 1)[1].strip()
        elif line.lower().startswith("quality approval:"):
            quality_value = line.split(":", 1)[1].strip().lower()
            quality_approval = quality_value in {"yes", "y", "true", "t", "1"}
        elif line.lower().startswith("description:"):
            description = line.split(":", 1)[1].strip()
        elif line.lower().startswith("change"):
            change_info = line.split(":", 1)[1].strip()
            changes.append(parse_change_line(change_info))

    if not ecn_id and lines:
        ecn_id = "ECN-INTAKE-001"
    if not title and lines:
        title = "ECN from intake"
    if not affected_assembly and lines:
        affected_assembly = "A-100"

    return {
        "ecnId": ecn_id,
        "title": title,
        "status": "DRAFT",
        "affectedAssembly": affected_assembly,
        "effectiveDate": "2026-09-01",
        "qualityApproval": quality_approval,
        "description": description,
        "changes": changes,
    }


def parse_change_line(change_text: str) -> Dict[str, Any]:
    parts = re.split(r"\s+", change_text.strip())
    action = None
    if parts and parts[0].lower() in {"replace", "remove", "add"}:
        action = parts[0].upper()
    elif parts and parts[0].lower() == "change":
        action = "CHANGE_QUANTITY"

    if action is None:
        return {"action": "ADD", "parentPartNumber": "", "oldPartNumber": "", "newPartNumber": "", "oldQuantity": 0, "newQuantity": 0, "uom": "EA"}

    tokens = [token for token in parts[1:] if token]
    old_part = ""
    new_part = ""
    old_quantity = 0
    new_quantity = 0
    uom = "EA"

    for token in tokens:
        if token.startswith("component"):
            continue
        if re.match(r"^[A-Z0-9-]+$", token) and token.startswith("C-") and not old_part:
            old_part = token
        elif re.match(r"^[A-Z0-9-]+$", token) and token.startswith("C-") and old_part and not new_part:
            new_part = token
        elif token.isdigit():
            if new_quantity == 0:
                new_quantity = int(token)
            else:
                old_quantity = int(token)
        elif token.upper() in {"EA", "EA."}:
            uom = "EA"

    if action == "REPLACE":
        return {
            "action": action,
            "parentPartNumber": "",
            "oldPartNumber": old_part,
            "newPartNumber": new_part,
            "oldQuantity": old_quantity or 1,
            "newQuantity": new_quantity or 1,
            "uom": uom,
        }

    if action == "REMOVE":
        return {
            "action": action,
            "parentPartNumber": "",
            "oldPartNumber": old_part,
            "newPartNumber": "",
            "oldQuantity": old_quantity or 1,
            "newQuantity": 0,
            "uom": uom,
        }

    if action == "ADD":
        return {
            "action": action,
            "parentPartNumber": "",
            "oldPartNumber": "",
            "newPartNumber": new_part or old_part,
            "oldQuantity": 0,
            "newQuantity": new_quantity or 1,
            "uom": uom,
        }

    return {
        "action": action,
        "parentPartNumber": "",
        "oldPartNumber": old_part,
        "newPartNumber": new_part,
        "oldQuantity": old_quantity or 1,
        "newQuantity": new_quantity or 1,
        "uom": uom,
    }


def _looks_like_ecn_text(text: str) -> bool:
    if not text:
        return False
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return bool(re.search(r"\bECN\b|\bTitle\b|Affected assembly|Quality approval|Change \d+:", normalized, flags=re.IGNORECASE))


def extract_text_from_path(input_path: Path | str) -> str:
    path = Path(input_path)
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md", ".rtf"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".eml":
        raw_bytes = path.read_bytes()
        return _extract_text_from_eml_bytes(raw_bytes)

    if suffix == ".pdf":
        raw_bytes = path.read_bytes()
        for module_name in ("pypdf", "PyPDF2", "pdfplumber"):
            if importlib.util.find_spec(module_name):
                try:
                    module = __import__(module_name)
                    if module_name in {"pypdf", "PyPDF2"}:
                        reader = module.PdfReader(str(path))
                        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
                        if _looks_like_ecn_text(extracted):
                            return extracted
                    if module_name == "pdfplumber":
                        with module.open(str(path)) as handle:
                            extracted = "\n".join(page.extract_text() or "" for page in handle.pages)
                            if _looks_like_ecn_text(extracted):
                                return extracted
                except Exception:
                    continue

        fallback = _extract_text_from_pdf_bytes(raw_bytes)
        if _looks_like_ecn_text(fallback):
            return fallback
        return ""

    raise ValueError(f"Unsupported input file type: {suffix}")


def _extract_text_from_eml_bytes(raw_bytes: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    body_parts = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "text" and part.get_content_disposition() != "attachment":
                body_parts.append(part.get_content())
    else:
        body_parts.append(message.get_content())
    return "\n".join(part for part in body_parts if part).strip()


_PDF_MAX_BYTES = 10 * 1024 * 1024   # 10 MB hard limit
_PDF_MAX_STREAMS = 256               # maximum number of streams to extract
_PDF_MAX_STREAM_BYTES = 512 * 1024  # maximum size of a single decompressed stream (512 KB)


def _extract_text_from_pdf_bytes(raw_bytes: bytes) -> str:
    if len(raw_bytes) > _PDF_MAX_BYTES:
        raw_bytes = raw_bytes[:_PDF_MAX_BYTES]

    marker = b"stream"
    chunks = []
    start = 0
    streams_read = 0

    while streams_read < _PDF_MAX_STREAMS:
        start_index = raw_bytes.find(marker, start)
        if start_index < 0:
            break
        stream_start = start_index + len(marker)
        end_index = raw_bytes.find(b"endstream", stream_start)
        if end_index < 0:
            break
        payload = raw_bytes[stream_start:end_index].lstrip(b"\r\n")
        if payload:
            try:
                if b"FlateDecode" in raw_bytes[max(0, start_index - 200): start_index + 80]:
                    decompressed = zlib.decompress(payload)
                    payload = decompressed[:_PDF_MAX_STREAM_BYTES]
            except Exception:
                pass
            if len(payload) > _PDF_MAX_STREAM_BYTES:
                payload = payload[:_PDF_MAX_STREAM_BYTES]
            text = payload.decode("latin-1", errors="ignore")
            text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
            if text:
                chunks.append(text)
        start = end_index + len(b"endstream")
        streams_read += 1

    if chunks:
        return "\n".join(chunks)
    return raw_bytes.decode("latin-1", errors="ignore")


def load_ecn_from_path(input_path: Path | str) -> Dict[str, Any]:
    return normalize_ecn_text(extract_text_from_path(input_path))


def load_ecns_from_imap(host: str, username: str, password: str, folder: str = "INBOX", limit: int = 5) -> List[Dict[str, Any]]:
    mail = imaplib.IMAP4_SSL(host)
    mail.login(username, password)
    mail.select(folder)
    _, message_ids = mail.search(None, "ALL")
    ids = [msg_id for msg_id in message_ids[0].split() if msg_id]
    ecns: List[Dict[str, Any]] = []

    for msg_id in ids[-limit:]:
        _, msg_data = mail.fetch(msg_id, "(RFC822)")
        if not msg_data:
            continue
        raw_message = b"".join(part[1] for part in msg_data if isinstance(part, tuple) and len(part) > 1)
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        body_parts = []
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_maintype() == "text" and part.get_content_disposition() != "attachment":
                    body_parts.append(part.get_content())
        else:
            body_parts.append(message.get_content())
        text = "\n".join(part for part in body_parts if part)
        ecns.append(normalize_ecn_text(text))

    mail.logout()
    return ecns


def build_input_files(normalized_ecn: Dict[str, Any], output_dir: Path, baseline_dir: Path | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir = baseline_dir or Path("data")

    parts_path = output_dir / "parts.csv"
    bom_path = output_dir / "master_bom.csv"
    header_path = output_dir / "ecn_header.csv"
    changes_path = output_dir / "ecn_changes.csv"

    if not parts_path.exists():
        parts_path.write_text((baseline_dir / "parts.csv").read_text(encoding="utf-8"), encoding="utf-8")
    if not bom_path.exists():
        bom_path.write_text((baseline_dir / "master_bom.csv").read_text(encoding="utf-8"), encoding="utf-8")

    with header_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ecnId", "title", "status", "affectedAssembly", "effectiveDate", "qualityApproval", "description"])
        writer.writerow([
            normalized_ecn["ecnId"],
            normalized_ecn["title"],
            normalized_ecn["status"],
            normalized_ecn["affectedAssembly"],
            normalized_ecn["effectiveDate"],
            "true" if normalized_ecn.get("qualityApproval") else "false",
            normalized_ecn["description"],
        ])

    with changes_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ecnId", "lineNumber", "action", "parentPartNumber", "oldPartNumber", "newPartNumber", "oldQuantity", "newQuantity", "uom"])
        for index, change in enumerate(normalized_ecn.get("changes", []), start=1):
            writer.writerow([
                normalized_ecn["ecnId"],
                str(index),
                change.get("action", "ADD"),
                normalized_ecn.get("affectedAssembly", ""),
                change.get("oldPartNumber", ""),
                change.get("newPartNumber", ""),
                change.get("oldQuantity", 0),
                change.get("newQuantity", 0),
                change.get("uom", "EA"),
            ])

    return output_dir
