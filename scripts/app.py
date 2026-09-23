
from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from pathlib import Path


print("=== app.py starting ===", flush=True)

# Resolve paths relative to repo root, not scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, jsonify, render_template, request

from scripts.ecn_checker import run_checks
from scripts.stages.intake import load_file
from scripts.precheck_pipeline import run_precheck
from scripts import evaluation_queries
from scripts.evaluation_store import (
    complete_precheck,
    connect_evaluation_db,
    create_session,
    initialise_schema,
    record_notification_attempt,
    start_precheck,
    store_evaluation_files,
)
from scripts.stages.validation_notification import send_validation_email




app = Flask(
    __name__,
    template_folder=os.path.join(ROOT, "templates"),
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB limit

ROLE_ALLOWED_EXTENSIONS = {
    "ecn_creator": {".csv", ".xls", ".xlsx", ".xlsm", ".pdf", ".eml", ".txt"},
    "bom_coordinator": {".csv", ".xls", ".xlsx", ".xlsm", ".xl"},
}


def allowed_file(filename: str, role: str = "ecn_creator") -> bool:
    if not filename or "." not in filename:
        return False
    ext = Path(filename).suffix.lower()
    return ext in ROLE_ALLOWED_EXTENSIONS.get(role, set())


def _csv_from_loaded_row(row: dict[str, object], header: list[str]) -> str:
    values = []
    for key in header:
        value = row.get(key, "")
        if isinstance(value, (int, float)):
            value = str(value)
        elif value is None:
            value = ""
        values.append(str(value).replace('"', '""'))
    return ",".join(header) + "\n" + ",".join(f'"{v}"' for v in values) + "\n"


def _normalise_uploaded_data(filename: str, payload: object, role: str) -> tuple[str, str]:
    stem = Path(filename).stem or "uploaded"
    if role == "ecn_creator":
        synthetic_name = f"{stem}_ecn_header.csv"
        if isinstance(payload, dict):
            ecn_number = str(
                payload.get("change_notice_number") or payload.get("ecn_number") or ""
            ).strip()
            title = str(payload.get("title") or "ECN Intake").strip()
            status = str(payload.get("status") or "draft").strip().lower()
            initiator = str(payload.get("author") or payload.get("initiator") or "Manual review").strip()
            date_value = str(payload.get("date") or payload.get("date_initiated") or "").strip()
            reason = str(payload.get("reason_for_change") or payload.get("reason") or payload.get("description") or "").replace('"', '""')
            description = str(payload.get("description") or "").replace('"', '""')
            csv_text = (
                'ecn_number,title,reason_for_change,description,status,initiator,date_initiated\n'
                f'"{ecn_number}","{title}","{reason}","{description}","{status}","{initiator}","{date_value}"\n'
            )
            return synthetic_name, csv_text
        if isinstance(payload, list):
            rows = payload or []
            row = rows[0] if rows else {}
            csv_text = (
                'ecn_number,title,reason_for_change,description,status,initiator,date_initiated\n'
                f'"{row.get("change_notice_number", row.get("ecn_number", ""))}",'
                f'"{row.get("title", "ECN Intake")}",'
                f'"{row.get("reason_for_change", row.get("reason", ""))}",'
                f'"{row.get("description", "")}",'
                f'"{row.get("status", "draft")}",'
                f'"{row.get("author", row.get("initiator", "Manual review"))}",'
                f'"{row.get("date", row.get("date_initiated", ""))}"\n'
            )
            return synthetic_name, csv_text
    synthetic_name = f"{stem}_bom.csv"
    if isinstance(payload, list):
        rows = payload or []
        csv_lines = ["part_number,parent_part,quantity,unit_of_measure"]
        for row in rows:
            part = str(row.get("part_number") or row.get("part") or "").strip()
            parent = str(row.get("parent_part") or row.get("parent") or "").strip()
            qty = str(row.get("quantity") or row.get("qty") or "1").strip()
            unit = str(row.get("unit") or row.get("unit_of_measure") or row.get("uom") or "ea").strip()
            if not part:
                continue
            csv_lines.append(f'"{part}","{parent}","{qty}","{unit}"')
        return synthetic_name, "\n".join(csv_lines) + "\n"
    if isinstance(payload, dict):
        part = str(payload.get("part_number") or payload.get("part") or "").strip()
        if not part:
            part = str(payload.get("item") or "").strip()
        parent = str(payload.get("parent_part") or payload.get("parent") or "").strip()
        qty = str(payload.get("quantity") or payload.get("qty") or "1").strip()
        unit = str(payload.get("unit") or payload.get("unit_of_measure") or payload.get("uom") or "ea").strip()
        csv_text = (
            'part_number,parent_part,quantity,unit_of_measure\n'
            f'"{part}","{parent}","{qty}","{unit}"\n'
        )
        return synthetic_name, csv_text
    return synthetic_name, "part_number,parent_part,quantity,unit_of_measure\n"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    """Provide a lightweight readiness check for the React development server."""
    return jsonify({"status": "ok"})


def _save_uploaded_file(file_storage) -> str:
    """Write an upload to a temporary path while preserving its original stem."""
    original = Path(file_storage.filename or "upload")
    with tempfile.NamedTemporaryFile(
        prefix=f"{original.stem}_",
        suffix=original.suffix.lower(),
        delete=False,
    ) as temporary:
        temporary.write(file_storage.read())
        return temporary.name


def _persist_precheck(
    tester_email: str,
    tester_name: str,
    packet: dict,
    uploaded_files: list[dict],
) -> dict:
    """Persist a completed pre-check when local PostgreSQL is configured."""
    if not os.environ.get("ECN_DB_PASSWORD"):
        return {"saved": False, "message": "Evaluation database is not configured."}

    with connect_evaluation_db() as connection:
        initialise_schema(connection)
        session_id = create_session(connection, tester_email, tester_name)
        attempt_id = start_precheck(connection, session_id)
        store_evaluation_files(connection, attempt_id, uploaded_files)
        duration = complete_precheck(
            connection,
            attempt_id,
            session_id,
            packet["gate"]["decision"],
            {"packet": packet},
        )
    return {"saved": True, "attempt_id": attempt_id, "duration_seconds": duration}


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


@app.route("/api/precheck", methods=["POST"])
def api_precheck():
    """Run the same staged pipeline used by the Streamlit upload workflow."""
    ecn_file = request.files.get("ecn")
    bom_file = request.files.get("bom")
    tester_email = request.form.get("tester_email", "").strip()
    tester_name = request.form.get("tester_name", "").strip()
    if ecn_file is None or not ecn_file.filename:
        return jsonify({"error": "An ECN file is required."}), 400
    if not tester_email:
        return jsonify({"error": "Tester email is required to save the evaluation."}), 400

    temporary_paths = []
    try:
        ecn_bytes = ecn_file.read()
        ecn_file.stream.seek(0)
        ecn_path = _save_uploaded_file(ecn_file)
        temporary_paths.append(ecn_path)
        uploaded_files = [{
            "role": "ecn",
            "filename": ecn_file.filename,
            "mime_type": ecn_file.mimetype,
            "bytes": ecn_bytes,
        }]
        bom_path = None
        if bom_file is not None and bom_file.filename:
            bom_bytes = bom_file.read()
            bom_file.stream.seek(0)
            bom_path = _save_uploaded_file(bom_file)
            temporary_paths.append(bom_path)
            uploaded_files.append({
                "role": "bom",
                "filename": bom_file.filename,
                "mime_type": bom_file.mimetype,
                "bytes": bom_bytes,
            })
        packet = run_precheck(ecn_path, bom_path)
        persistence = _persist_precheck(tester_email, tester_name, packet, uploaded_files)
        return jsonify(_precheck_response(packet, len(uploaded_files), persistence))
    except Exception as exc:
        return jsonify({"error": f"The pre-check could not be completed: {exc}"}), 422
    finally:
        for temporary_path in temporary_paths:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass




@app.route("/api/notification", methods=["POST"])
def api_notification():
    """Send an auditable report from a tester-owned saved pre-check."""
    body = request.get_json(silent=True) or {}
    attempt_id = body.get("attempt_id")
    tester_email = str(body.get("tester_email", "")).strip()
    recipient = str(body.get("recipient", "")).strip()
    if not attempt_id or not tester_email or not recipient:
        return jsonify({"error": "attempt_id, tester_email, and recipient are required."}), 400

    try:
        with connect_evaluation_db() as connection:
            detail = evaluation_queries.get_attempt_detail(
                connection,
                int(attempt_id),
                {"email": tester_email, "role": "TESTER"},
            )
        if detail is None:
            return jsonify({"error": "Evaluation attempt was not found."}), 404

        payload = detail.get("payload", {})
        packet = payload.get("packet", {}) if isinstance(payload, dict) else {}
        decision = str(packet.get("gate", {}).get("decision", "")).upper()
        if decision == "FAIL" and recipient.casefold() != tester_email.casefold():
            return jsonify({"error": "Failed results can only be emailed to the tester."}), 403
        if decision not in {"PASS", "FAIL"}:
            return jsonify({"error": "The saved result has no emailable decision."}), 422

        result = send_validation_email(packet, recipient)
        status = "sent" if result.get("sent") else "failed"
        with connect_evaluation_db() as connection:
            record_notification_attempt(
                connection,
                int(attempt_id),
                "validation_report",
                recipient,
                status,
                result.get("message"),
            )
        return jsonify({
            "sent": bool(result.get("sent")),
            "message": result.get("message", "Email could not be sent."),
        })
    except Exception as exc:
        return jsonify({"error": f"The notification could not be sent: {type(exc).__name__}."}), 422



@app.route("/upload", methods=["POST"])
def upload():



    role = request.form.get("role", "ecn_creator")
    uploaded = request.files.getlist("files")


    if not uploaded or all(f.filename == "" for f in uploaded):
        return jsonify({"error": "No files selected."}), 400

    results = []
    file_data = {}
    accepted_files = 0

    for f in uploaded:
        name = f.filename or ""
        if not name or not allowed_file(name, role):
            results.append({
                "file": name or "unnamed",
                "issues": [{"rule": "UPLOAD", "severity": "error",
                             "message": f"Only {', '.join(sorted(ROLE_ALLOWED_EXTENSIONS.get(role, set())))} files are accepted for this role."}]
            })
            continue

        accepted_files += 1
        file_bytes = f.read()
        ext = Path(name).suffix.lower()
        try:
            if ext == ".csv":
                content = file_bytes.decode("utf-8-sig")
                file_data[name] = content
            else:
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
                try:
                    parsed = load_file(tmp_path)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                synthetic_name, csv_text = _normalise_uploaded_data(name, parsed, role)
                file_data[synthetic_name] = csv_text
        except Exception as exc:  # pragma: no cover - defensive validation path
            results.append({
                "file": name,
                "issues": [{"rule": "UPLOAD", "severity": "error",
                             "message": f"Unable to parse {name}: {exc}"}]
            })
            continue

    check_results = run_checks(file_data, role=role)
    results.extend(check_results)

    summary = {
        "total_files": accepted_files,
        "total_issues": sum(len(r.get("issues", [])) for r in results),
        "errors": sum(1 for r in results for i in r.get("issues", []) if i["severity"] == "error"),
        "warnings": sum(1 for r in results for i in r.get("issues", []) if i["severity"] == "warning"),
    }

    return jsonify({"summary": summary, "results": results})


if __name__ == "__main__":
    print(f"Templates folder: {os.path.join(ROOT, 'templates')}", flush=True)
    print(f"templates/index.html exists: {os.path.exists(os.path.join(ROOT, 'templates', 'index.html'))}", flush=True)
    app.run(debug=True, port=5000)