"""Application workflow for an authenticated ECN pre-check submission."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.evaluation_store import (
    complete_precheck,
    connect_evaluation_db,
    create_session,
    initialise_schema,
    start_precheck,
    store_evaluation_files,
)
from scripts.precheck_pipeline import run_precheck


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _save_uploaded_file(filename: str, content: bytes) -> str:
    """Write an upload to a temporary path while preserving its original stem."""
    original = Path(filename or "upload")
    with tempfile.NamedTemporaryFile(
        prefix=f"{original.stem}_",
        suffix=original.suffix.lower(),
        delete=False,
    ) as temporary:
        temporary.write(content)
        return temporary.name


def _persist_precheck(
    tester_email: str,
    tester_name: str,
    packet: dict,
    uploaded_files: list[dict[str, Any]],
    source_status: str = "DRAFT",
    *,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> dict:
    """Persist a completed pre-check when local PostgreSQL is configured."""
    if not os.environ.get("ECN_DB_PASSWORD"):
        return {"saved": False, "message": "Evaluation database is not configured."}

    filename = next(
        (str(file.get("filename", "")) for file in uploaded_files if file.get("role") == "ecn"),
        "",
    )
    match = re.search(r"(?<!\d)(\d{7})(?!\d)", Path(filename).name)
    attempt_name = f"{match.group(1)}_MBOM_{source_status}" if match else "legacy"

    with connect_evaluation_db() as connection:
        initialise_schema(connection)
        session_id = create_session(connection, tester_email, tester_name)
        attempt_id = start_precheck(
            connection,
            session_id,
            source_status=source_status,
            attempt_name=attempt_name,
            started_at=started_at,
        )
        store_evaluation_files(connection, attempt_id, uploaded_files)
        duration = complete_precheck(
            connection,
            attempt_id,
            session_id,
            packet["gate"]["decision"],
            {"packet": packet},
            completed_at=completed_at,
        )

    return {
        "saved": True,
        "attempt_id": attempt_id,
        "attempt_name": attempt_name,
        "ecn_number": match.group(1) if match else None,
        "source_status": source_status,
        "duration_seconds": duration,
    }


def _precheck_response(packet: dict, file_count: int, persistence: dict | None = None) -> dict:
    gate = packet.get("gate", {})
    findings = []
    for category in ("blockers", "part_issues", "conflict_alerts", "warnings"):
        for finding in gate.get(category, []):
            findings.append({
                "rule": finding.get("rule_id") or finding.get("flag_type") or finding.get("type", category),
                "severity": str(finding.get("severity", "advisory")).lower(),
                "message": finding.get("message") or finding.get("detail", ""),
                "location": finding.get("location"),
                "evidence": finding.get("evidence"),
                "category": category,
            })
    errors = sum(1 for finding in findings if finding["severity"] in {"error", "fail"})
    warnings = sum(1 for finding in findings if finding["severity"] == "warning")
    return {
        "decision": gate.get("decision", "FAIL"),
        "summary": {
            "total_files": file_count,
            "total_issues": len(findings),
            "errors": errors,
            "warnings": warnings,
        },
        "findings": findings,
        "persistence": persistence or {"saved": False},
    }


def run_precheck_workflow(
    ecn_file,
    bom_file,
    *,
    tester_email: str,
    tester_name: str,
    source_status: str = "DRAFT",
) -> dict:
    """Run validation, save its evaluation snapshot, and return the API result.

    The caller validates authentication, authorization, and request fields. This
    workflow owns upload staging, validation, persistence, timing, and cleanup.
    """
    started_at = _utc_now()
    temporary_paths = []
    uploaded_files = []

    try:
        ecn_bytes = ecn_file.read()
        ecn_file.stream.seek(0)
        ecn_path = _save_uploaded_file(ecn_file.filename, ecn_bytes)
        temporary_paths.append(ecn_path)
        uploaded_files.append({
            "role": "ecn",
            "filename": ecn_file.filename,
            "mime_type": ecn_file.mimetype,
            "bytes": ecn_bytes,
        })

        bom_path = None
        if bom_file is not None and bom_file.filename:
            bom_bytes = bom_file.read()
            bom_file.stream.seek(0)
            bom_path = _save_uploaded_file(bom_file.filename, bom_bytes)
            temporary_paths.append(bom_path)
            uploaded_files.append({
                "role": "bom",
                "filename": bom_file.filename,
                "mime_type": bom_file.mimetype,
                "bytes": bom_bytes,
            })

        packet = run_precheck(ecn_path, bom_path)
        completed_at = _utc_now()
        persistence = _persist_precheck(
            tester_email,
            tester_name,
            packet,
            uploaded_files,
            source_status=source_status,
            started_at=started_at,
            completed_at=completed_at,
        )
        return _precheck_response(packet, len(uploaded_files), persistence)
    finally:
        for temporary_path in temporary_paths:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
