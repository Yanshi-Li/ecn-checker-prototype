from __future__ import annotations
import csv
import io
import os
import sys
import tempfile
from pathlib import Path

print("=== app.py starting ===", flush=True)

# Must come before importing ecn_checker
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, render_template, request

from ecn_checker import run_checks
from intake import load_file

# Resolve paths relative to repo root, not scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
            ecn_number = str(payload.get("ecn_id") or payload.get("ecn_number") or "").strip()
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
                f'"{row.get("ecn_id", row.get("ecn_number", ""))}",'
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