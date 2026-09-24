
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

from flask import Flask, Response, jsonify, render_template, request, send_file, session



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
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)
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


def _current_user() -> dict | None:
    """Return the authenticated user held in Flask's signed session cookie."""
    user = session.get("user")
    if not isinstance(user, dict) or not user.get("email") or not user.get("role"):
        return None
    return user


@app.route("/api/auth/session")
def api_auth_session():
    user = _current_user()
    if user is None:
        return jsonify({"user": None}), 401
    return jsonify({"user": user})


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip()
    password = str(body.get("password", ""))
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
    try:
        with connect_evaluation_db() as connection:
            initialise_schema(connection)
            evaluation_queries.ensure_configured_admin(
                connection,
                os.environ.get("REVIEWER_ADMIN_EMAIL", ""),
                os.environ.get("REVIEWER_ADMIN_PASSWORD", ""),
            )
            user = evaluation_queries.authenticate_user(connection, email, password)
    except Exception:
        return jsonify({"error": "Login is unavailable. Check the evaluation database configuration."}), 503
    if user is None:
        return jsonify({"error": "Email or password is incorrect."}), 401
    session.clear()
    session["user"] = user
    return jsonify({"user": user})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return "", 204





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
    user = _current_user()

    if user is None:
        return jsonify({"error": "Sign in before running a pre-check."}), 401
    if user["role"] not in {"TESTER", "ADMINISTRATOR"}:
        return jsonify({"error": "Only tester or administrator accounts can run a pre-check."}), 403
    tester_email = str(user["email"])
    tester_name = str(user.get("display_name", ""))

    if ecn_file is None or not ecn_file.filename:
        return jsonify({"error": "An ECN file is required."}), 400


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




def _reviewer_user() -> tuple[dict | None, tuple[object, int] | None]:
    """Return the signed-in reviewer or an appropriate JSON error response."""
    user = _current_user()
    if user is None:
        return None, (jsonify({"error": "Sign in before opening the reviewer area."}), 401)
    if user.get("role") not in {"REVIEWER", "ADMINISTRATOR"}:
        return None, (jsonify({"error": "Reviewer or administrator access is required."}), 403)
    return user, None


def _administrator_user() -> tuple[dict | None, tuple[object, int] | None]:
    user = _current_user()
    if user is None:
        return None, (jsonify({"error": "Sign in before opening administrator tools."}), 401)
    if user.get("role") != "ADMINISTRATOR":
        return None, (jsonify({"error": "Administrator access is required."}), 403)
    return user, None


@app.route("/api/admin/reviewers")
def api_admin_reviewers():
    user, error = _administrator_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            return jsonify({"reviewers": evaluation_queries.list_users(connection, "REVIEWER")})
    except Exception:
        return jsonify({"error": "Reviewer accounts are unavailable."}), 503


@app.route("/api/admin/assignable-attempts")
def api_admin_assignable_attempts():
    user, error = _administrator_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            return jsonify({"attempts": evaluation_queries.list_assignable_attempts(connection)})
    except Exception:
        return jsonify({"error": "Assignable attempts are unavailable."}), 503


@app.route("/api/admin/assignments", methods=["POST"])
def api_admin_assign_reviewer():
    user, error = _administrator_user()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    try:
        attempt_id = int(body.get("attempt_id"))
        reviewer_id = int(body.get("reviewer_id"))
        with connect_evaluation_db() as connection:
            evaluation_queries.assign_reviewer(connection, attempt_id, reviewer_id, int(user["id"]))
            assignments = evaluation_queries.list_assignments(connection, attempt_id)
        return jsonify({"saved": True, "assignments": assignments})
    except (TypeError, ValueError):
        return jsonify({"error": "attempt_id and reviewer_id are required."}), 400
    except Exception:
        return jsonify({"error": "The reviewer assignment could not be saved."}), 503


@app.route("/api/admin/disputes")
def api_admin_disputes():
    user, error = _administrator_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            return jsonify({"attempts": evaluation_queries.list_disputed_attempts(connection)})
    except Exception:
        return jsonify({"error": "Disputed attempts are unavailable."}), 503


@app.route("/api/admin/attempts/<int:attempt_id>/comparison")
def api_admin_comparison(attempt_id: int):
    user, error = _administrator_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            comparison = evaluation_queries.get_reviewer_comparison(connection, attempt_id)
        if comparison is None:
            return jsonify({"error": "Evaluation attempt was not found."}), 404
        return jsonify(comparison)
    except Exception:
        return jsonify({"error": "Reviewer comparison is unavailable."}), 503


@app.route("/api/admin/attempts/<int:attempt_id>/resolve", methods=["POST"])
def api_admin_resolve_dispute(attempt_id: int):
    user, error = _administrator_user()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    try:
        with connect_evaluation_db() as connection:
            evaluation_queries.resolve_review_dispute(connection, attempt_id, user, str(body.get("comment", "")))
            status = evaluation_queries.get_review_status(connection, attempt_id)
        return jsonify({"saved": True, "review_status": status})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "The dispute could not be resolved."}), 503


@app.route("/api/admin/review-report")
def api_admin_review_report():
    user, error = _administrator_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            return jsonify(evaluation_queries.get_cross_attempt_review_report(connection))
    except Exception:
        return jsonify({"error": "The review report is unavailable."}), 503


@app.route("/api/admin/evaluation-export")
def api_admin_evaluation_export():
    user, error = _administrator_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            rows = evaluation_queries.list_attempts(connection, {
                "system_decision": request.args.get("decision", "ALL"),
                "tester": request.args.get("tester", ""),
                "case_identifier": request.args.get("ecn", ""),
            })
        if not rows:
            csv_text = "attempt_id,system_decision,started_at,completed_at,duration_seconds,case_identifier,tester_email,tester_name,tester_judgement,agreement\n"
        else:
            import csv as csv_module
            output = io.StringIO()
            fieldnames = list(rows[0].keys())
            writer = csv_module.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            csv_text = output.getvalue()
        return Response(csv_text, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=evaluation-export.csv"})
    except Exception:
        return jsonify({"error": "The evaluation export is unavailable."}), 503


@app.route("/api/admin/evaluation-summary")
def api_admin_evaluation_summary():
    """Return aggregate evaluation metrics for administrators."""
    user = _current_user()
    if user is None:
        return jsonify({"error": "Sign in before opening the administrator dashboard."}), 401
    if user.get("role") != "ADMINISTRATOR":
        return jsonify({"error": "Administrator access is required."}), 403
    try:
        with connect_evaluation_db() as connection:
            initialise_schema(connection)
            summary = evaluation_queries.get_evaluation_summary(connection, {
                "system_decision": request.args.get("decision", "ALL"),
                "tester": request.args.get("tester", ""),
                "case_identifier": request.args.get("ecn", ""),
            })
        return jsonify(summary)
    except Exception:
        return jsonify({"error": "The evaluation summary is unavailable."}), 503


@app.route("/api/reviewer/queue")
def api_reviewer_queue():
    """Return a filtered, paginated review queue."""
    user, error = _reviewer_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            initialise_schema(connection)
            if not request.args:
                attempts = evaluation_queries.list_review_queue(connection, user)
                result = {"attempts": attempts}
            else:
                result = evaluation_queries.list_review_queue_page(
                    connection,
                    user,
                    {
                        "page": request.args.get("page", 1, type=int),
                        "page_size": request.args.get("page_size", 20, type=int),
                        "decision": request.args.get("decision", "ALL"),
                        "review_status": request.args.get("review_status", "ALL"),
                        "tester": request.args.get("tester", ""),
                    },
                )
        return jsonify(result)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid queue pagination or filter values."}), 400
    except Exception:
        return jsonify({"error": "The reviewer queue is unavailable."}), 503




@app.route("/api/reviewer/attempts/<int:attempt_id>")
def api_reviewer_attempt_detail(attempt_id: int):
    """Return one authorized review attempt and its findings."""
    user, error = _reviewer_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            detail = evaluation_queries.get_attempt_detail(connection, attempt_id, user)
            if detail is not None:
                detail["reviewer_submission"] = evaluation_queries.get_reviewer_submission(
                    connection, attempt_id, int(user["id"])
                )
                if user.get("role") == "ADMINISTRATOR":
                    detail["assignments"] = evaluation_queries.list_assignments(connection, attempt_id)
                    detail["reviewer_comparison"] = evaluation_queries.get_reviewer_comparison(connection, attempt_id)
        if detail is None:
            return jsonify({"error": "Evaluation attempt was not found."}), 404
        return jsonify(detail)
    except PermissionError:
        return jsonify({"error": "This attempt is not assigned to you."}), 403
    except Exception:
        return jsonify({"error": "The evaluation attempt is unavailable."}), 503


@app.route("/api/reviewer/attempts/<int:attempt_id>/files/<role>")
def api_reviewer_file(attempt_id: int, role: str):
    """Download an original ECN or BOM after authorization."""
    user, error = _reviewer_user()
    if error:
        return error
    try:
        with connect_evaluation_db() as connection:
            original = evaluation_queries.get_original_file(connection, attempt_id, role, user)
        if original is None:
            return jsonify({"error": "The requested file was not found."}), 404
        return send_file(
            io.BytesIO(original["content"]),
            mimetype=original["mime_type"],
            as_attachment=True,
            download_name=original["filename"],
        )
    except PermissionError:
        return jsonify({"error": "This attempt is not assigned to you."}), 403
    except ValueError:
        return jsonify({"error": "The file role is invalid."}), 400
    except Exception:
        return jsonify({"error": "The original file is unavailable."}), 503


@app.route("/api/reviewer/attempts/<int:attempt_id>/judgement", methods=["POST"])
def api_reviewer_judgement(attempt_id: int):
    """Store an independent reviewer judgement for an assigned attempt."""
    user, error = _reviewer_user()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    raw_rules = body.get("rule_judgements", {})
    if not isinstance(raw_rules, dict):
        return jsonify({"error": "rule_judgements must be an object."}), 400
    rule_judgements = {}
    for rule_id, value in raw_rules.items():
        if not isinstance(value, dict):
            return jsonify({"error": "Each rule judgement must contain judgement and comment."}), 400
        rule_judgements[str(rule_id)] = (
            str(value.get("judgement", "")),
            str(value.get("comment", "")),
        )
    try:
        with connect_evaluation_db() as connection:
            evaluation_queries.submit_reviewer_judgement(
                connection,
                attempt_id,
                user,
                str(body.get("judgement", "")),
                str(body.get("comment", "")),
                rule_judgements,
            )
            status = evaluation_queries.get_review_status(connection, attempt_id)
        return jsonify({"saved": True, "review_status": status})
    except PermissionError:
        return jsonify({"error": "This attempt is not assigned to you."}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "The reviewer judgement could not be saved."}), 503


@app.route("/api/tester/attempts/<int:attempt_id>/judgement", methods=["POST"])
def api_tester_judgement(attempt_id: int):
    user = _current_user()
    if user is None:
        return jsonify({"error": "Sign in before submitting a tester judgement."}), 401
    if user.get("role") not in {"TESTER", "ADMINISTRATOR"}:
        return jsonify({"error": "Tester access is required."}), 403
    body = request.get_json(silent=True) or {}
    raw_rules = body.get("rule_judgements", {})
    if not isinstance(raw_rules, dict):
        return jsonify({"error": "rule_judgements must be an object."}), 400
    try:
        rule_judgements = {
            str(rule_id): (str(value.get("judgement", "")), str(value.get("comment", "")))
            for rule_id, value in raw_rules.items() if isinstance(value, dict)
        }
        with connect_evaluation_db() as connection:
            detail = evaluation_queries.get_attempt_detail(connection, attempt_id, user)
            if detail is None:
                return jsonify({"error": "Evaluation attempt was not found."}), 404
            evaluation_queries.save_tester_judgement(
                connection, attempt_id, str(body.get("judgement", "")),
                str(body.get("explanation", "")), str(user.get("email", "")), rule_judgements,
            )
        return jsonify({"saved": True})
    except PermissionError:
        return jsonify({"error": "This evaluation is not owned by the tester."}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "The tester judgement could not be saved."}), 503


@app.route("/api/notification", methods=["POST"])
def api_notification():

    """Send an auditable report from a tester-owned saved pre-check."""
    body = request.get_json(silent=True) or {}
    attempt_id = body.get("attempt_id")
    user = _current_user()
    recipient = str(body.get("recipient", "")).strip()
    if user is None:
        return jsonify({"error": "Sign in before sending a report."}), 401
    if user["role"] not in {"TESTER", "ADMINISTRATOR"}:
        return jsonify({"error": "Only tester or administrator accounts can send a report."}), 403
    tester_email = str(user["email"])

    if not attempt_id or not recipient:
        return jsonify({"error": "attempt_id and recipient are required."}), 400

    try:
        with connect_evaluation_db() as connection:
            detail = evaluation_queries.get_attempt_detail(
                connection,
                int(attempt_id),
                {"email": tester_email, "role": user["role"]},
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