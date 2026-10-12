
from __future__ import annotations

import io
import os
import sys
from pathlib import Path




print("=== app.py starting ===", flush=True)

# Resolve paths relative to repo root, not scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, Response, jsonify, request, send_file, send_from_directory, session
from psycopg.errors import UniqueViolation

from scripts import precheck_workflow



from scripts import evaluation_queries
from scripts.evaluation_store import (
    claim_notification_attempt,
    complete_notification_attempt,
    connect_evaluation_db,
    initialise_schema,
)


from scripts.stages.validation_notification import send_validation_email
from scripts.evaluation_auth import can_test, normalise_role




def _load_local_env() -> None:
    """Load local development settings without printing credential values."""
    env_path = Path(ROOT) / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env()


DIST = os.path.join(ROOT, "frontend", "dist")

app = Flask(
    __name__,
    template_folder=os.path.join(ROOT, "templates"),
    static_folder=DIST,
    static_url_path="",
)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB limit





@app.route("/")
def index():
    return send_from_directory(DIST, "index.html")


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





@app.route("/api/precheck", methods=["POST"])
def api_precheck():
    """Validate request access and delegate the pre-check workflow."""
    ecn_file = request.files.get("ecn")
    bom_file = request.files.get("bom")
    user = _current_user()

    if user is None:
        return jsonify({"error": "Sign in before running a pre-check."}), 401
    if not can_test(user["role"]):
        return jsonify({"error": "Tester access is required to run a pre-check."}), 403
    if ecn_file is None or not ecn_file.filename:
        return jsonify({"error": "An ECN file is required."}), 400

    source_status = str(request.form.get("source_status", "DRAFT")).strip().upper()
    if source_status not in {"DRAFT", "COMPLETED"}:
        return jsonify({"error": "source_status must be DRAFT or COMPLETED."}), 400

    try:
        result = precheck_workflow.run_precheck_workflow(
            ecn_file,
            bom_file,
            tester_email=str(user["email"]),
            tester_name=str(user.get("display_name", "")),
            source_status=source_status,
        )
        persistence = result.get("persistence", {})
        if result.get("decision") == "FAIL" and persistence.get("saved") and persistence.get("attempt_id"):
            packet = {
                "header": {"change_notice_number": persistence.get("ecn_number") or "N/A"},
                "gate": {
                    "decision": "FAIL",
                    "blockers": [
                        {"rule_id": item.get("rule"), "severity": item.get("severity")}
                        for item in result.get("findings", [])
                    ],
                },
            }
            result["notification"] = _deliver_notification(
                int(persistence["attempt_id"]), "validation_report", str(user["email"]), packet,
            )
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": f"The pre-check could not be completed: {type(exc).__name__}."}), 422






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


@app.route("/api/admin/users", methods=["POST"])
def api_admin_create_user():
    """Create an application account after enforcing administrator access."""
    _, error = _administrator_user()
    if error:
        return error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "A JSON account payload is required."}), 400

    email = str(body.get("email", "")).strip().casefold()
    display_name = str(body.get("display_name", "")).strip()
    password = str(body.get("password", ""))
    raw_role = str(body.get("role", "")).strip()
    if not email or "@" not in email or any(character.isspace() for character in email):
        return jsonify({"error": "A valid email address is required."}), 400
    if not display_name:
        return jsonify({"error": "A display name is required."}), 400
    if not password.strip():
        return jsonify({"error": "A non-empty password is required."}), 400
    try:
        role = normalise_role(raw_role)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        with connect_evaluation_db() as connection:
            initialise_schema(connection)
            user_id = evaluation_queries.create_user(
                connection, email, display_name, password, role
            )
        return jsonify({
            "user": {
                "id": user_id,
                "email": email,
                "display_name": display_name,
                "role": role,
            },
        }), 201
    except UniqueViolation:
        return jsonify({"error": "An account with that email already exists."}), 409
    except Exception:
        return jsonify({"error": "The account could not be created."}), 503


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
            initialise_schema(connection)
            evaluation_queries.assign_reviewer(connection, attempt_id, reviewer_id, int(user["id"]))
            assignments = evaluation_queries.list_assignments(connection, attempt_id)
            detail = evaluation_queries.get_attempt_detail(connection, attempt_id, user)
        notification = None
        if detail and str(detail.get("system_decision", "")).upper() == "PASS":
            assigned = next((
                item for item in assignments
                if int(item.get("reviewer_id", -1)) == reviewer_id and item.get("status") != "REVOKED"
            ), None)
            payload = detail.get("payload", {})
            packet = payload.get("packet", {}) if isinstance(payload, dict) else {}
            if assigned:
                notification = _deliver_notification(
                    attempt_id, "validation_report", str(assigned.get("email", "")), packet,
                )
        return jsonify({"saved": True, "assignments": assignments, "notification": notification})
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
                "decision": request.args.get("decision", "ALL"),
                "source_status": request.args.get("source_status", "ALL"),
                "tester": request.args.get("tester", ""),
                "ecn_number": request.args.get("ecn_number", ""),
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

        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=evaluation-export.csv"},
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "The evaluation export is unavailable."}), 503






@app.route("/api/admin/evaluation-attempts")
def api_admin_evaluation_attempts():
    """List evaluation attempts using the shared dashboard filters."""
    user, error = _administrator_user()
    if error:
        return error

    try:
        with connect_evaluation_db() as connection:
            initialise_schema(connection)
            attempts = evaluation_queries.list_attempts(connection, {




                "ecn_number": request.args.get("ecn_number", ""),
                "source_status": request.args.get("source_status", "ALL"),
                "decision": request.args.get("decision", "ALL"),
                "tester": request.args.get("tester", ""),
            })

        return jsonify({"attempts": attempts})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Evaluation attempts are unavailable."}), 503


@app.route("/api/tester/evaluation-attempts")
def api_tester_evaluation_attempts():
    """List only the signed-in tester's attempts with dashboard-compatible filters."""
    user = _current_user()
    if user is None:
        return jsonify({"error": "Sign in before viewing evaluation attempts."}), 401
    if not can_test(user.get("role")):
        return jsonify({"error": "Tester access is required."}), 403
    try:
        with connect_evaluation_db() as connection:
            initialise_schema(connection)
            attempts = evaluation_queries.list_attempts(connection, {



                "ecn_number": request.args.get("ecn_number", ""),
                "source_status": request.args.get("source_status", "ALL"),
                "decision": request.args.get("decision", "ALL"),
                "tester_email": str(user.get("email", "")),
            })
        return jsonify({"attempts": attempts})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Evaluation attempts are unavailable."}), 503


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




                "decision": request.args.get("decision", "ALL"),
                "source_status": request.args.get("source_status", "ALL"),
                "ecn_number": request.args.get("ecn_number", ""),
                "tester": request.args.get("tester", ""),
            })


        return jsonify(summary)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
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




@app.route("/api/tester/attempts/<int:attempt_id>")
def api_tester_attempt_detail(attempt_id: int):
    """Return one saved attempt after verifying it belongs to the signed-in tester."""
    user = _current_user()
    if user is None:
        return jsonify({"error": "Sign in before viewing an evaluation attempt."}), 401
    if user.get("role") != "TESTER":
        return jsonify({"error": "Tester access is required."}), 403

    try:
        with connect_evaluation_db() as connection:
            detail = evaluation_queries.get_attempt_detail(connection, attempt_id, user)
        if detail is None:
            return jsonify({"error": "Evaluation attempt was not found."}), 404
        return jsonify(detail)
    except PermissionError:
        return jsonify({"error": "This evaluation is not owned by the tester."}), 403
    except Exception:
        return jsonify({"error": "The evaluation attempt is unavailable."}), 503


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

    if not can_test(user.get("role")):
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


def _deliver_notification(attempt_id: int, kind: str, recipient: str, packet: dict) -> dict[str, object]:
    """Claim, send, and audit one deterministic delivery without affecting pre-check results."""
    from hashlib import sha256

    normalized_recipient = recipient.strip().casefold()
    key = sha256(f"{attempt_id}|{kind}|{normalized_recipient}".encode("utf-8")).hexdigest()
    try:
        with connect_evaluation_db() as connection:
            initialise_schema(connection)
            claimed, existing_status = claim_notification_attempt(
                connection, attempt_id, kind, recipient, key,
            )
        if not claimed:
            if existing_status == "sent":
                return {"sent": True, "status": "sent", "message": "Validation result notification was already sent."}
            return {"sent": False, "status": existing_status, "message": "A notification for this result is already in progress."}

        result = send_validation_email(packet, recipient)
        status = "sent" if result.get("sent") else "failed"
        with connect_evaluation_db() as connection:
            complete_notification_attempt(
                connection, attempt_id, kind, recipient, key, status,
                None if result.get("sent") else "Email delivery failed.",
            )
        return {
            "sent": bool(result.get("sent")),
            "status": str(result.get("status", status)),
            "message": str(result.get("message", "Email could not be sent.")),
        }
    except Exception:
        return {"sent": False, "status": "failed", "message": "Email could not be sent; the saved pre-check is unchanged."}


@app.route("/api/notification", methods=["POST"])
def api_notification():
    """Retry a saved-result email to a server-derived, authorized recipient."""
    user = _current_user()
    if user is None:
        return jsonify({"error": "Sign in before retrying a notification."}), 401
    body = request.get_json(silent=True) or {}
    try:
        attempt_id = int(body.get("attempt_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "attempt_id is required."}), 400

    try:
        with connect_evaluation_db() as connection:
            detail = evaluation_queries.get_attempt_detail(connection, attempt_id, user)
            if detail is None:
                return jsonify({"error": "Evaluation attempt was not found."}), 404
            packet_payload = detail.get("payload", {})
            packet = packet_payload.get("packet", {}) if isinstance(packet_payload, dict) else {}
            decision = str(packet.get("gate", {}).get("decision", "")).upper()
            if decision == "FAIL":
                if user.get("role") != "TESTER":
                    return jsonify({"error": "Only the submitting tester can retry a failed-result notification."}), 403
                recipient = str(user.get("email", ""))
                recipients = [recipient]
            elif decision == "PASS":
                if user.get("role") != "ADMINISTRATOR":
                    return jsonify({"error": "Administrator access is required to retry a passed-result notification."}), 403
                assignments = evaluation_queries.list_assignments(connection, attempt_id)
                recipients = [str(item.get("email", "")) for item in assignments if item.get("status") != "REVOKED"]
            else:
                return jsonify({"error": "The saved result has no emailable decision."}), 422
        if not recipients:
            return jsonify({"error": "Assign an active next checker before retrying this notification."}), 409
        outcomes = [_deliver_notification(attempt_id, "validation_report", recipient, packet) for recipient in recipients]
        return jsonify({"notifications": outcomes, "sent": all(item["sent"] for item in outcomes)})
    except PermissionError:
        return jsonify({"error": "This evaluation is not accessible to this account."}), 403
    except Exception:
        return jsonify({"error": "The notification could not be retried."}), 503






if __name__ == "__main__":
    app.run(debug=True, port=5000)