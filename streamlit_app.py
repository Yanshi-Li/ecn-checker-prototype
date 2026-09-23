"""Public Streamlit interface for the ECN Checker pipeline."""

import csv
import datetime as dt

import io
import json
import hmac
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
STAGES = SCRIPTS / "stages"
ECN_FILE_TYPES = ["csv", "xlsx", "xls", "pdf", "html", "htm", "eml"]
BOM_FILE_TYPES = ["csv", "xlsx", "xls", "pdf"]

# Make the repository package importable in direct Streamlit and test sessions.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.batch_intake import BatchPreparation, build_batch_from_paths  # noqa: E402
from scripts.batch_orchestration import BatchCase, BatchResult, run_batch  # noqa: E402
from scripts import evaluation_queries  # noqa: E402

from scripts.evaluation_store import (  # noqa: E402
    assign_bom_input,
    complete_evaluation_batch,
    complete_precheck,
    connect_evaluation_db,
    create_bom_input,
    create_evaluation_batch,
    create_logical_ecn,
    create_precheck_case,
    create_session,
    fail_precheck,
    initialise_schema,
    record_notification_attempt,
    start_precheck,
    store_evaluation_files,
    update_precheck_case_status,
)







from scripts.stages import (
    ai_advisory as ai_advisory_mod,
    context_engine as context_engine_mod,
    email_notification as email_notification_mod,
    intake as intake_mod,
    merge_step as merge_step_mod,
    rule_engine as rule_engine_mod,
    validation_notification as validation_notification_mod,
)


run_intake = intake_mod.run_intake
run_rule_engine = rule_engine_mod.run_rule_engine
run_ai_advisory = ai_advisory_mod.run_ai_advisory
run_context_engine = context_engine_mod.run_context_engine
log_approved_change = context_engine_mod.log_approved_change
run_merge_step = merge_step_mod.run_merge_step
send_fail_email = email_notification_mod.send_fail_email
send_pass_email = email_notification_mod.send_pass_email
send_validation_email = validation_notification_mod.send_validation_email


def _get_config_value(key: str, default: str = "") -> str:
    """Read Streamlit secrets first, then fall back to local environment values."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is not None:
            value = st.secrets.get(key)
            if value is not None:
                return str(value).strip()
    except Exception:
        # No Streamlit runtime/secrets configured: retain local environment support.
        pass

    return os.environ.get(key, default).strip()


def _evaluation_db_config() -> dict[str, str]:
    """Read evaluation database settings without exposing the password."""
    return {
        key: _get_config_value(key)
        for key in (
            "ECN_DB_HOST",
            "ECN_DB_PORT",
            "ECN_DB_NAME",
            "ECN_DB_USER",
            "ECN_DB_PASSWORD",
        )
        if _get_config_value(key)
    }


def _password_matches(submitted_password: str, configured_password: str) -> bool:
    """Compare non-empty passwords without leaking a partial-match timing signal."""
    return bool(configured_password) and hmac.compare_digest(
        submitted_password, configured_password
    )


def _authenticate() -> None:
    """Record a successful password entry for the current Streamlit session."""
    configured_password = _get_config_value("APP_PASSWORD")
    submitted_password = st.session_state.get("app_password_entry", "")

    if _password_matches(submitted_password, configured_password):
        st.session_state["app_authenticated"] = True
        st.session_state.pop("app_auth_error", None)
        st.session_state.pop("app_password_entry", None)
    else:
        st.session_state["app_authenticated"] = False
        st.session_state["app_auth_error"] = True


def _require_access() -> bool:
    """Render the password gate and return whether this session is authorized."""
    if st.session_state.get("app_authenticated", False):
        return True

    configured_password = _get_config_value("APP_PASSWORD")
    st.title("ECN Checker Access")
    if not configured_password:
        st.error("APP_PASSWORD must be configured before this app can be used.")
        return False

    st.text_input(
        "Password",
        type="password",
        key="app_password_entry",
        on_change=_authenticate,
    )
    if st.session_state.get("app_auth_error", False):
        st.error("Incorrect password.")
    return False


ECN_MANUAL_FIELDS = [
    "change_notice_number",
    "name_of_change",
    "reason_for_change",
    "description_of_change",
    "products_affected",
    "change_actions",
    "date",
    "project",
    "product_group",
    "change_category",
    "associated_a3",
    "a3_number",
    "checker",
    "reviewer",
    "chief_engineer",
    "bom_coordinator",
]
BOM_MANUAL_FIELDS = [
    "line_number",
    "part_number",
    "description",
    "quantity",
    "unit",
    "action",
    "parent_part_no",
]


def _csv_text(rows: list[dict], fieldnames: list[str]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({field: row.get(field, "") for field in fieldnames} for row in rows)
    return output.getvalue()


def manual_ecn_csv(values: dict[str, object]) -> str:
    """Serialize canonical manual ECN intake fields for the existing loader."""
    row = {
        field: "" if values.get(field) is None else str(values.get(field))
        for field in ECN_MANUAL_FIELDS
    }
    return _csv_text([row], ECN_MANUAL_FIELDS)


def manual_bom_csv(rows: list[dict[str, object]]) -> str:
    """Serialize canonical manual BOM rows for the existing loader."""
    normalized = []
    for index, row in enumerate(rows, start=1):
        normalized.append(
            {
                "line_number": row.get("line_number") or index,
                "part_number": row.get("part_number", ""),
                "description": row.get("description", ""),
                "quantity": row.get("quantity", "1"),
                "unit": row.get("unit", "EA"),
                "action": row.get("action", ""),
                "parent_part_no": row.get("parent_part_no", ""),
            }
        )
    return _csv_text(normalized, BOM_MANUAL_FIELDS)


def validate_manual_input(
    values: dict[str, object], bom_rows: list[dict[str, object]]
) -> list[str]:
    """Return user-facing errors before invoking the authoritative pipeline."""
    errors = [
        f"{field.replace('_', ' ').title()} is required."
        for field in intake_mod.REQUIRED_ECN_FIELDS
        if not str(values.get(field, "")).strip()
    ]
    if not bom_rows:
        errors.append("At least one BOM row is required.")
    for index, row in enumerate(bom_rows, start=1):
        if not str(row.get("part_number", "")).strip():
            errors.append(f"BOM row {index} requires a part number.")
        quantity = str(row.get("quantity", "")).strip()
        try:
            if not quantity or float(quantity) <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"BOM row {index} quantity must be a positive number.")
    return errors


def _write_text(text: str, suffix: str = ".csv") -> str:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", suffix=suffix, delete=False
    ) as temp_file:
        temp_file.write(text)
        return temp_file.name


def _write_upload(uploaded_file) -> str:
    """Persist an upload while retaining its identifying filename in the path.

    Batch intake matches ECN and BOM files by exact seven-digit identifiers in
    their filenames. A random temporary filename would discard that identifier,
    so use the uploaded stem as the temporary-file prefix.
    """
    original_name = Path(uploaded_file.name)
    suffix = original_name.suffix.lower()
    prefix = f"{original_name.stem}_"
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=suffix, delete=False) as temp_file:
        temp_file.write(uploaded_file.getvalue())
        return temp_file.name





def batch_preview_rows(preparation: BatchPreparation) -> list[dict[str, str]]:
    """Return a display-oriented preview of safe ECN/BOM mappings."""
    ecns = {ecn.key: ecn for ecn in preparation.batch.logical_ecns}
    bom_by_ecn: dict[str, list] = {}
    for bom in preparation.batch.bom_inputs:
        target = preparation.batch.mappings.get(bom.key) if preparation.batch.mappings else None
        if target:
            bom_by_ecn.setdefault(target, []).append(bom)

    rows: list[dict[str, str]] = []
    for ecn_key in sorted(ecns):
        boms = bom_by_ecn.get(ecn_key, [])
        if not boms:
            rows.append(
                {
                    "ECN": ecn_key,
                    "ECN file": str(ecns[ecn_key].metadata.get("source_file", "")),
                    "BOM": "—",
                    "BOM state": "ABSENT",
                    "Status": "Ready (ECN only)",
                }
            )
            continue
        for bom in boms:
            rows.append(
                {
                    "ECN": ecn_key,
                    "ECN file": str(ecns[ecn_key].metadata.get("source_file", "")),
                    "BOM": bom.key,
                    "BOM state": bom.state,
                    "Status": "Ready",
                }
            )
    return rows


def batch_error_rows(preparation: BatchPreparation) -> list[dict[str, str]]:
    """Return intake errors in a shape suitable for a Streamlit table."""
    return [
        {"Role": error.role.upper(), "File": str(error.path), "Problem": error.message}
        for error in preparation.errors
    ]


def _execute_batch_case(case: BatchCase) -> dict[str, object]:
    """Run one normalized batch case through the authoritative pipeline."""
    ecn_path = str(case.logical_ecn.metadata["source_file"])
    bom_path = str(case.bom.metadata["source_file"]) if case.bom else None
    packet = _run_pipeline(ecn_path, bom_path)
    return {"decision": packet["gate"]["decision"], "packet": packet}


def _start_batch_evaluation(
    tester_email: str,
    tester_name: str,
    batch,
) -> dict[str, object] | None:
    """Create the PostgreSQL records needed to persist every batch case."""
    db_config = _evaluation_db_config()
    if not db_config.get("ECN_DB_PASSWORD"):
        return None

    try:
        with connect_evaluation_db(db_config) as connection:
            initialise_schema(connection)
            session_email = tester_email.strip()
            session_id = st.session_state.get("evaluation_session_id")
            if (
                session_id is None
                or st.session_state.get("evaluation_session_tester_email") != session_email
            ):
                session_id = create_session(connection, session_email, tester_name.strip())
                st.session_state["evaluation_session_id"] = session_id
                st.session_state["evaluation_session_tester_email"] = session_email

            batch_id = create_evaluation_batch(
                connection,
                session_id,
                {"case_count": len(batch.logical_ecns), "source": "streamlit"},
            )
            ecn_ids = {
                ecn.key: create_logical_ecn(connection, batch_id, ecn.key, ecn.metadata)
                for ecn in batch.logical_ecns
            }
            bom_ids = {}
            for bom in batch.bom_inputs:
                bom_id = create_bom_input(
                    connection, batch_id, bom.key, bom.state, bom.metadata
                )
                bom_ids[bom.key] = bom_id
                target = (batch.mappings or {}).get(bom.key, bom.suggested_ecn_key)
                if target:
                    assign_bom_input(connection, bom_id, ecn_ids[target])

            case_ids = {}
            for ecn in batch.logical_ecns:
                assigned = [
                    bom
                    for bom in batch.bom_inputs
                    if (batch.mappings or {}).get(bom.key, bom.suggested_ecn_key)
                    == ecn.key
                ]
                for bom in assigned or [None]:
                    case_id = create_precheck_case(
                        connection,
                        batch_id,
                        ecn_ids[ecn.key],
                        bom_ids.get(bom.key) if bom else None,
                    )
                    case_ids[f"{ecn.key}:{bom.key if bom else 'ECN_ONLY'}"] = case_id
            return {"session_id": session_id, "batch_id": batch_id, "case_ids": case_ids}
    except Exception:
        return None


def _batch_case_files(case: BatchCase) -> list[dict[str, object]]:
    """Read the source files for one batch case for audit persistence."""
    files: list[dict[str, object]] = []
    sources = (
        ("ecn", case.logical_ecn.metadata.get("source_file")),
        ("bom", case.bom.metadata.get("source_file") if case.bom else None),
    )
    for role, source in sources:
        if not source:
            continue
        source_path = Path(str(source))
        if source_path.exists():
            files.append(
                {
                    "role": role,
                    "filename": source_path.name,
                    "bytes": source_path.read_bytes(),
                }
            )
    return files


def _execute_persisted_batch_case(
    case: BatchCase, persistence: dict[str, object]
) -> dict[str, object]:
    """Run a case and persist its attempt without hiding validation errors."""
    db_config = _evaluation_db_config()
    case_id = persistence["case_ids"][case.case_id]
    session_id = persistence["session_id"]

    with connect_evaluation_db(db_config) as connection:
        attempt_id = start_precheck(connection, session_id, case_id)

    try:
        result = _execute_batch_case(case)
    except Exception as exc:
        with connect_evaluation_db(db_config) as connection:
            files = _batch_case_files(case)
            if files:
                store_evaluation_files(connection, attempt_id, files)
            fail_precheck(connection, attempt_id, session_id, str(exc))
            update_precheck_case_status(connection, case_id, "ERROR")
        raise

    gate = result["packet"]["gate"]
    payload = {
        "packet": result["packet"],
        "case_id": case.case_id,
        "blocker_count": len(gate.get("blockers", [])),
        "part_issue_count": len(gate.get("part_issues", [])),
        "warning_count": len(gate.get("warnings", [])),
    }

    with connect_evaluation_db(db_config) as connection:
        files = _batch_case_files(case)
        if files:
            store_evaluation_files(connection, attempt_id, files)
        complete_precheck(connection, attempt_id, session_id, result["decision"], payload)
        update_precheck_case_status(connection, case_id, result["decision"])

    return result


def _complete_batch_evaluation(
    persistence: dict[str, object] | None, status: str

) -> None:
    """Mark the batch complete, allowing the UI result to remain available."""
    if persistence is None:
        return
    try:
        with connect_evaluation_db(_evaluation_db_config()) as connection:
            complete_evaluation_batch(connection, persistence["batch_id"], status)
    except Exception:
        st.warning("Batch results are available, but the final status could not be saved.")


def _render_batch_result(result: BatchResult) -> None:

    """Render independent batch outcomes and their validation findings."""
    counts = result.metrics.latest_counts
    st.subheader("Batch results")
    st.write(
        f"Completed: {counts.get('PASS', 0)} PASS, "
        f"{counts.get('FAIL', 0)} FAIL, "
        f"{counts.get('ERROR', 0)} ERROR"
    )
    for case in result.cases:
        bom_label = case.bom.key if case.bom else "ECN only"
        with st.expander(f"{case.logical_ecn.key} — {bom_label} — {case.status}"):
            st.caption(f"Case: {case.case_id}")
            if case.status == "ERROR":
                st.error(case.error)
                continue
            packet = case.result.get("packet", {}) if case.result else {}
            gate = packet.get("gate", {})
            _render_findings("Blockers", gate.get("blockers", []))
            _render_findings("Part Issues", gate.get("part_issues", []))
            _render_findings("Conflict Alerts", gate.get("conflict_alerts", []))
            _render_findings("Warnings", gate.get("warnings", []))
            _render_ai_notes(gate.get("ai_notes", {}))


def _run_pipeline(ecn_path: str, bom_path: str | None = None) -> dict:
    """Run the same validation stages used by the command-line orchestrator."""
    packet = run_intake(ecn_path, bom_path)
    packet = run_rule_engine(packet)
    packet = run_ai_advisory(packet)
    packet = run_context_engine(packet)
    packet = run_merge_step(packet)
    log_approved_change(packet)
    return packet


def _display_value(value: object) -> str:
    """Convert structured finding values into Arrow-compatible text."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _finding_rows(findings: list[dict]) -> list[dict]:
    """Convert gate findings to an Arrow-compatible table shape."""
    return [
        {
            "Finding": _display_value(
                finding.get("rule_id")
                or finding.get("flag_type")
                or finding.get("type", "—")
            ),
            "Severity": _display_value(finding.get("severity", "ADVISORY")),
            "Message": _display_value(finding.get("message") or finding.get("detail", "")),
            "Location": _display_value(finding.get("location")),
            "Evidence": _display_value(finding.get("evidence")),
        }
        for finding in findings
    ]



def _render_findings(title: str, findings: list[dict]) -> None:
    with st.expander(f"{title} ({len(findings)})"):
        if findings:
            st.dataframe(_finding_rows(findings), hide_index=True, width="stretch")
        else:
            st.info(f"No {title.lower()} found.")


def _streamlit_secrets() -> dict[str, object]:
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def _render_manual_form() -> tuple[dict[str, object], list[dict[str, object]]] | None:
    st.subheader("Manual intake")
    st.caption("Enter the canonical ECN intake fields used by the validation pipeline.")
    values: dict[str, object] = {}
    required = {
        "change_notice_number": "Change Notice Number",
        "name_of_change": "Name of Change",
        "reason_for_change": "Reason for Change",
        "description_of_change": "Description of Change",
        "products_affected": "Products Affected",
        "change_actions": "Change Actions",
    }
    for field, label in required.items():
        values[field] = (
            st.text_area(label, key=f"manual_{field}")
            if field
            in {
                "reason_for_change",
                "description_of_change",
                "products_affected",
                "change_actions",
            }
            else st.text_input(label, key=f"manual_{field}")
        )
    date_value = st.date_input("Date", value=None, key="manual_date")
    values["date"] = (
        date_value.isoformat() if isinstance(date_value, (dt.date, dt.datetime)) else ""
    )

    with st.expander("Optional canonical fields"):
        optional = {
            "project": "Project",
            "product_group": "Product Group",
            "change_category": "Change Category",
            "associated_a3": "Associated A3",
            "a3_number": "A3 Number",
            "checker": "Checker",
            "reviewer": "Reviewer",
            "chief_engineer": "Chief Engineer",
            "bom_coordinator": "BOM Coordinator",
        }
        for field, label in optional.items():
            values[field] = st.text_input(label, key=f"manual_{field}")

    st.subheader("BOM lines")
    default_rows = pd.DataFrame(
        [
            {
                "line_number": 1,
                "part_number": "",
                "description": "",
                "quantity": "1",
                "unit": "EA",
                "action": "",
                "parent_part_no": "",
            }
        ]
    )
    edited = st.data_editor(
        default_rows,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "line_number": st.column_config.NumberColumn("Line Number", min_value=1, step=1),
            "quantity": st.column_config.TextColumn("Quantity"),
        },
        key="manual_bom_editor",
    )
    rows = edited.fillna("").to_dict(orient="records")
    return values, rows


def _render_ai_notes(ai_notes: dict) -> None:
    flags = ai_notes.get("flags", [])
    with st.expander(f"AI Notes ({len(flags)})"):
        availability = "AI response" if ai_notes.get("ai_available") else "Rule-based advisory"
        st.caption(availability)
        if ai_notes.get("recommendation"):
            st.write(ai_notes["recommendation"])
        if flags:
            st.dataframe(_finding_rows(flags), hide_index=True, width="stretch")
        else:
            st.info("No AI advisory flags found.")


def _render_tester_judgement(packet: dict) -> None:
    """Let the identified tester record an independent overall and rule review."""
    attempt_id = st.session_state.get("evaluation_attempt_id")
    tester_email = str(st.session_state.get("evaluation_tester_email", "")).strip()
    if not attempt_id or not tester_email:
        return

    gate = packet.get("gate", {})
    findings = [
        finding
        for category in ("blockers", "part_issues", "conflict_alerts", "warnings")
        for finding in gate.get(category, []) or []
        if isinstance(finding, dict)
    ]
    st.divider()
    st.subheader("Record your judgement")
    st.caption("Your judgement is stored separately from the system decision.")
    rule_judgements: dict[str, tuple[str, str]] = {}
    for index, finding in enumerate(findings):
        rule_id = str(finding.get("rule_id") or finding.get("flag_type") or "").strip()
        if not rule_id:
            continue
        with st.expander(f"{rule_id} — {finding.get('message', 'Finding')}"):
            value = st.selectbox(
                "Rule judgement",
                ("CORRECT", "INCORRECT", "UNCLEAR", "NOT_APPLICABLE"),
                key=f"tester_rule_judgement_{attempt_id}_{index}",
            )
            comment = st.text_area(
                "Rule comment", key=f"tester_rule_comment_{attempt_id}_{index}"
            )
            rule_judgements[rule_id] = (value, comment)
    overall = st.selectbox(
        "Overall judgement", ("PASS", "FAIL"), key=f"tester_overall_judgement_{attempt_id}"
    )
    explanation = st.text_area(
        "Overall explanation", key=f"tester_overall_explanation_{attempt_id}"
    )
    if st.button("Submit tester judgement", key=f"submit_tester_judgement_{attempt_id}"):
        try:
            with connect_evaluation_db(_evaluation_db_config()) as connection:
                evaluation_queries.save_tester_judgement(
                    connection,
                    int(attempt_id),
                    overall,
                    explanation,
                    tester_email,
                    rule_judgements,
                )
            st.success("Tester judgement submitted.")
        except Exception:
            st.error("Tester judgement could not be saved.")


def _start_evaluation_precheck(tester_email: str, tester_name: str):

    """Create or reuse the current session and start a pre-check attempt."""
    db_config = _evaluation_db_config()
    if not db_config.get("ECN_DB_PASSWORD"):
        return None

    session_email = tester_email.strip()
    try:
        with connect_evaluation_db(db_config) as connection:
            # Keep local setup self-contained: the dedicated application role
            # owns this database and can create the evaluation tables.
            initialise_schema(connection)
            session_id = st.session_state.get("evaluation_session_id")
            if (
                session_id is None
                or st.session_state.get("evaluation_session_tester_email") != session_email
            ):
                session_id = create_session(connection, session_email, tester_name.strip())
                st.session_state["evaluation_session_id"] = session_id
                st.session_state["evaluation_session_tester_email"] = session_email

            return session_id, start_precheck(connection, session_id)
    except Exception:
        return None


def _complete_evaluation_precheck(
    evaluation: tuple[int, int] | None,
    system_decision: str,
    result_payload: dict[str, object],
    files: list[dict[str, object]] | None = None,
):
    """Persist completion data and return duration, or None if persistence fails."""
    if evaluation is None:
        return None
    session_id, attempt_id = evaluation
    try:
        with connect_evaluation_db(_evaluation_db_config()) as connection:
            if files:
                store_evaluation_files(connection, attempt_id, files)
            duration = complete_precheck(
                connection, attempt_id, session_id, system_decision, result_payload
            )
        st.session_state["evaluation_attempt_id"] = attempt_id
        return duration
    except Exception:
        return None


def _record_notification_result(result: dict[str, object], kind: str) -> None:

    """Persist notification outcome without affecting the validation result."""
    attempt_id = st.session_state.get("evaluation_attempt_id")
    config = _evaluation_db_config()
    if not attempt_id or not config.get("ECN_DB_PASSWORD"):
        return
    recipients = result.get("recipients") or []
    recipient = ", ".join(str(value) for value in recipients if value)
    if not recipient:
        return
    status = "sent" if result.get("sent") else "requested" if result.get("dry_run") else "failed"
    try:
        with connect_evaluation_db(config) as connection:
            record_notification_attempt(
                connection,
                int(attempt_id),
                kind,
                recipient,
                status,
                result.get("error"),
            )
    except Exception:
        # Notification audit failure must never hide the validation outcome.
        pass


def _reviewer_user() -> dict[str, object] | None:
    """Authenticate a reviewer or administrator for the protected area."""
    config = _evaluation_db_config()
    if not config.get("ECN_DB_PASSWORD"):
        st.info("Reviewer data is unavailable: configure ECN_DB_PASSWORD.")
        return None
    try:
        with connect_evaluation_db(config) as connection:
            initialise_schema(connection)
            admin_email = _get_config_value("REVIEWER_ADMIN_EMAIL")
            admin_password = _get_config_value("REVIEWER_ADMIN_PASSWORD")
            if admin_email and admin_password:
                evaluation_queries.ensure_configured_admin(connection, admin_email, admin_password)
    except Exception:
        st.warning("Reviewer authentication is temporarily unavailable.")
        return None

    user = st.session_state.get("reviewer_user")
    if user:
        st.caption(f"Signed in as {user['display_name']} ({user['role']})")
        if st.button("Sign out", key="reviewer_sign_out"):
            st.session_state.pop("reviewer_user", None)
            st.rerun()
        return user

    st.subheader("Reviewer sign in")
    email = st.text_input("Reviewer email", key="reviewer_login_email")
    password = st.text_input("Reviewer password", type="password", key="reviewer_login_password")
    if st.button("Sign in", key="reviewer_sign_in"):
        try:
            with connect_evaluation_db(config) as connection:
                user = evaluation_queries.authenticate_user(connection, email, password)
        except Exception:
            user = None
        if user:
            st.session_state["reviewer_user"] = user
            st.rerun()
        st.error("Invalid reviewer credentials.")
    return None


def reviewer_metric_cards(summary: dict[str, object]) -> list[tuple[str, str]]:
    """Format the compact, reviewer-facing summary metrics."""
    return [
        ("Attempts", str(summary["total_attempts"])),
        ("PASS", f"{summary['pass_count']} ({summary['pass_percentage']}%)"),
        ("FAIL", f"{summary['fail_count']} ({summary['fail_percentage']}%)"),
        ("Agreement", f"{summary['agreement_percentage']}%"),
        ("Avg check", f"{summary['average_duration_seconds']} s"),
    ]


def _filtered_attempts(
    attempts: list[dict], decision: str, reviewer_status: str, tester: str
) -> list[dict]:
    """Filter the visible queue without changing reviewer access controls."""
    tester = tester.strip().lower()
    return [
        attempt for attempt in attempts
        if (decision == "All" or attempt.get("system_decision") == decision)
        and (reviewer_status == "All" or attempt.get("review_status") == reviewer_status)
        and (not tester or tester in str(attempt.get("tester_name") or attempt.get("tester_email") or "").lower())
    ]


def _render_reviewer_dashboard(user: dict[str, object]) -> None:
    """Render the protected reviewer queue and administrator view."""
    st.header("Reviewer dashboard")
    st.caption("System decisions and reviewer judgements are stored separately.")
    config = _evaluation_db_config()
    try:
        with connect_evaluation_db(config) as connection:
            queue = evaluation_queries.list_review_queue(connection, user)

            if user["role"] == "ADMINISTRATOR":
                with st.expander("Administrator tools", expanded=False):
                    st.markdown("**Create reviewer account**")
                    new_email = st.text_input("Reviewer email", key="new_reviewer_email")
                    new_name = st.text_input("Reviewer display name", key="new_reviewer_name")
                    new_password = st.text_input("Temporary reviewer password", type="password", key="new_reviewer_password")
                    if st.button("Create reviewer", key="create_reviewer"):
                        try:
                            evaluation_queries.create_user(connection, new_email, new_name, new_password, "REVIEWER")
                            st.success("Reviewer account created.")
                        except Exception as exc:
                            st.error(f"Reviewer account could not be created: {exc}")

                    reviewers = evaluation_queries.list_users(connection, "REVIEWER")
                    assignable = evaluation_queries.list_assignable_attempts(connection)
                    if reviewers and assignable:
                        st.markdown("**Assign completed attempt**")
                        reviewer_options = {f"{row['display_name']} ({row['email']})": row for row in reviewers}
                        attempt_options = {f"Attempt {row['attempt_id']} — {row['system_decision']} — {row['tester_email']}": row for row in assignable}
                        selected_reviewer_label = st.selectbox("Reviewer", list(reviewer_options), key="assignment_reviewer")
                        selected_attempt_label = st.selectbox("Attempt", list(attempt_options), key="assignment_attempt")
                        if st.button("Assign attempt", key="assign_attempt"):
                            selected_reviewer = reviewer_options[selected_reviewer_label]
                            selected_attempt = attempt_options[selected_attempt_label]
                            evaluation_queries.assign_reviewer(connection, int(selected_attempt["attempt_id"]), int(selected_reviewer["id"]), int(user["id"]))
                            st.success("Attempt assigned.")
                    elif not reviewers:
                        st.info("Create a reviewer before assigning attempts.")
                    else:
                        st.info("No completed attempts are available for assignment.")

                decision = st.selectbox("System decision", evaluation_queries.DECISIONS)

                tester = st.text_input("Tester name or email")
                agreement = st.selectbox("Agreement", evaluation_queries.AGREEMENT_STATES)
                filters = {"system_decision": decision, "tester": tester, "agreement": agreement}
                summary = evaluation_queries.get_evaluation_summary(connection, filters)
                metric_columns = st.columns(5)
                for column, (label, value) in zip(
                    metric_columns, reviewer_metric_cards(summary)
                ):
                    column.metric(label, value)

                cross_attempt = evaluation_queries.get_cross_attempt_review_report(connection)
                st.subheader("Cross-attempt reviewer report")
                st.write({
                    "Reviewed attempts": cross_attempt["reviewed_attempt_count"],
                    "Reviewer submissions": cross_attempt["reviewer_submission_count"],
                    "Overall agreement": f"{cross_attempt['overall_agreement_count']} ({cross_attempt['overall_agreement_percentage']}%)",
                                        "Overall disagreement": cross_attempt["overall_disagreement_count"],
                    "Disputed attempts": cross_attempt["disputed_attempt_count"],

                    "Rule judgements": cross_attempt["rule_judgement_count"],
                    "UNCLEAR rule judgements": cross_attempt["unclear_count"],
                    "NOT_APPLICABLE rule judgements": cross_attempt["not_applicable_count"],
                    "Rule disagreements": f"{cross_attempt['rule_disagreement_count']} ({cross_attempt['rule_disagreement_percentage']}%)",
                })

                attempts = evaluation_queries.list_attempts(connection, filters)
            else:  # reviewer queue
                attempts = queue
            st.subheader("Review queue")
            filter_columns = st.columns(3)
            queue_decision = filter_columns[0].selectbox("Result", ["All", "PASS", "FAIL"], key="review_queue_decision")
            statuses = sorted({str(row.get("review_status", "?")) for row in attempts})
            queue_status = filter_columns[1].selectbox("Review status", ["All", *statuses], key="review_queue_status")
            queue_tester = filter_columns[2].text_input("Tester", key="review_queue_tester")
            attempts = _filtered_attempts(attempts, queue_decision, queue_status, queue_tester)
            if not attempts:
                st.info("No review attempts match the selected filters.")
                return
            queue_column, _detail_column = st.columns((1, 2))
            queue_column.dataframe([{"Attempt": row["attempt_id"], "Tester": row.get("tester_name") or row.get("tester_email"), "Result": row["system_decision"], "Status": row.get("review_status", "?")} for row in attempts], hide_index=True, width="stretch")
            selected = queue_column.selectbox("Open attempt", [row["attempt_id"] for row in attempts])
            detail = evaluation_queries.get_attempt_detail(connection, int(selected), user)

            if not detail:
                return
            _detail_column.subheader(f"Attempt {detail['attempt_id']}")
            _detail_column.metric("System result", detail["system_decision"])
            _detail_column.write(
                f"Tester: {detail.get('tester_name') or detail.get('tester_email') or 'Not recorded'}"
            )
            _detail_column.caption(
                f"Checking duration: {detail.get('duration_seconds') or 'Not recorded'} seconds"
            )


            review_status = evaluation_queries.get_review_status(connection, int(selected))  # status


            own_submission = (
                None
                if user["role"] == "ADMINISTRATOR"
                else evaluation_queries.get_reviewer_submission(
                    connection, int(selected), int(user["id"])
                )
            )
            rule_report = (
                evaluation_queries.get_rule_judgement_report(connection, int(selected))
                if user["role"] == "ADMINISTRATOR" or own_submission
                else []
            )
            st.subheader(f"Attempt {detail['attempt_id']} — {detail['system_decision']}")
            if user["role"] != "ADMINISTRATOR" and not own_submission:
                st.info("Submit your review to see the aggregate reviewer judgements.")
            if rule_report:

                st.subheader("Rule-level reviewer report")
                st.dataframe(
                    [
                        {
                            "Rule": row["rule_id"],
                            "Judgements": row["judgement_count"],
                            "Correct": row["correct_count"],
                            "Incorrect": row["incorrect_count"],
                            "Unclear": row["unclear_count"],
                            "Not applicable": row["not_applicable_count"],
                            "Disagreement": "Yes" if row["disagreement"] else "No",
                        }
                        for row in rule_report
                    ],
                    hide_index=True,
                    width="stretch",
                )
            st.write({"Tester": detail.get("tester_name") or detail.get("tester_email"), "Started": detail.get("started_at"), "Completed": detail.get("completed_at"), "Checking duration (seconds)": detail.get("duration_seconds"), "Review status": review_status["status"], "Assigned reviewers": review_status["assigned_count"], "Submitted reviews": review_status["submitted_count"]})
            if review_status["status"] == "DISPUTED":
                st.error("Reviewer judgements conflict. Administrator resolution is required.")
                if user["role"] == "ADMINISTRATOR":
                    resolution = st.text_area("Dispute resolution explanation", key=f"resolution_{selected}")
                    if st.button("Resolve dispute", key=f"resolve_dispute_{selected}"):
                        evaluation_queries.resolve_review_dispute(connection, int(selected), user, resolution)
                        st.success("Dispute resolved and recorded in audit history.")
                        st.rerun()

            st.subheader("Pre-check details")
            payload = detail.get("payload", {})
            packet = payload.get("packet", {}) if isinstance(payload, dict) else {}
            header = packet.get("header", {}) if isinstance(packet, dict) else {}
            detail_columns = st.columns(2)
            detail_columns[0].markdown("**ECN**")
            detail_columns[0].write(header.get("change_notice_number") or "Not recorded")
            detail_columns[1].markdown("**Change**")
            detail_columns[1].write(header.get("name_of_change") or "Not recorded")
            st.subheader("Findings and evidence")
            st.dataframe(_finding_rows(detail.get("findings", [])), hide_index=True, width="stretch")
            for file in detail.get("files", []):
                original = evaluation_queries.get_original_file(connection, int(selected), file["role"], user)
                if original:
                    st.download_button(f"Download {file['role'].upper()} — {file['filename']}", original["content"], file_name=original["filename"], mime=original["mime_type"], key=f"download_{selected}_{file['role']}")
            st.subheader("Review findings")
            rule_judgements: dict[str, tuple[str, str]] = {}
            for index, finding in enumerate(detail.get("findings", [])):
                rule_id = str(finding.get("rule_id") or finding.get("flag_type") or "").strip()
                if not rule_id:
                    continue
                with st.expander(f"{rule_id} — {finding.get('message', 'Finding')}"):
                    rule_value = st.selectbox(
                        "Rule judgement",
                        ("CORRECT", "INCORRECT", "UNCLEAR", "NOT_APPLICABLE"),
                        key=f"rule_judgement_{selected}_{index}",
                    )
                    rule_comment = st.text_area("Rule comment", key=f"rule_comment_{selected}_{index}")
                    rule_judgements[rule_id] = (rule_value, rule_comment)

            st.subheader("Submit reviewer judgement")
            judgement = st.selectbox("Overall judgement", ("PASS", "FAIL"), key=f"reviewer_judgement_{selected}")
            comment = st.text_area("Reviewer comment", key=f"reviewer_comment_{selected}")
            if st.button("Submit reviewer judgement", key=f"submit_reviewer_{selected}"):
                evaluation_queries.submit_reviewer_judgement(
                    connection, int(selected), user, judgement, comment, rule_judgements
                )
                st.success("Reviewer judgement submitted.")

    except Exception:
        st.warning("Reviewer data is temporarily unavailable. Tester intake can still be used.")


def _legacy_render_reviewer_dashboard() -> None:
    """Retained for compatibility with callers of the old dashboard helper."""
    st.header("Reviewer dashboard")
    st.info("Sign in through the Reviewer dashboard workflow.")

def main() -> None:

    st.set_page_config(page_title="ECN Checker", page_icon="📋", layout="wide")
        # Reviewer access is protected by database-backed role authentication.
    st.title("ECN Checker")

    workflow = st.radio("Workflow", ["Tester intake", "Reviewer dashboard"], horizontal=True, key="workflow_mode")

    if workflow == "Reviewer dashboard":

        user = _reviewer_user()
        if user:
            _render_reviewer_dashboard(user)
        return


    st.subheader("Tester identification")
    tester_email = st.text_input("Tester email", key="evaluation_tester_email")
    tester_name = st.text_input("Tester name (optional)", key="evaluation_tester_name")
    st.caption("Your email identifies this evaluation session; it is stored with the results.")

    mode = st.radio(
        "Input method",
        ["Upload files", "Batch pre-check", "Manual intake"],
        horizontal=True,
        key="input_mode",
    )
    temporary_paths: list[str] = []
    can_run = bool(tester_email.strip())
    batch_preparation: BatchPreparation | None = None
    manual_input = None
    ecn_file = None
    bom_file = None

    if mode in {"Upload files", "Batch pre-check"}:
        batch_mode = mode == "Batch pre-check"
        upload_column, bom_column = st.columns(2)
        with upload_column:
            ecn_upload = st.file_uploader(
                "Step 1 — Upload ECN file(s)",
                type=ECN_FILE_TYPES,
                accept_multiple_files=batch_mode,
                help="CSV, Excel, PDF, HTML, or EML files are supported by the intake stage.",
            )
        with bom_column:
            bom_upload = st.file_uploader(
                "Step 2 — Upload BOM file(s)",
                type=BOM_FILE_TYPES,
                accept_multiple_files=batch_mode,
                help="CSV, Excel, or PDF files are supported by the intake stage.",
            )

                
        
        

        if batch_mode:


            ecn_files = ecn_upload or []

            bom_files = bom_upload or []
            can_prepare = can_run and bool(ecn_files)
            if st.button("Prepare Batch Mapping", disabled=not can_prepare):
                batch_paths: list[str] = []
                try:
                    batch_paths = [
                        *[_write_upload(upload) for upload in ecn_files],
                        *[_write_upload(upload) for upload in bom_files],
                    ]
                    ecn_count = len(ecn_files)
                    batch_preparation = build_batch_from_paths(
                        batch_paths[:ecn_count],
                        batch_paths[ecn_count:],
                    )
                    st.session_state["batch_preparation"] = batch_preparation
                except Exception as exc:
                    st.error(f"The batch could not be prepared: {exc}")
                    st.session_state.pop("batch_preparation", None)
                finally:
                    for path in batch_paths:
                        Path(path).unlink(missing_ok=True)

            batch_preparation = st.session_state.get("batch_preparation")
            if batch_preparation is not None:
                st.subheader("Batch mapping preview")
                if batch_preparation.errors:
                    st.error("Resolve the intake errors before running this batch.")
                    st.dataframe(
                        batch_error_rows(batch_preparation),
                        hide_index=True,
                        width="stretch",
                    )
                else:
                    st.dataframe(
                        batch_preview_rows(batch_preparation),
                        hide_index=True,
                        width="stretch",
                    )
                    st.info(
                        "Review the mapping above, then click Run Checks to execute "
                        "each ECN/BOM case independently."
                    )
                can_run = can_run and not batch_preparation.errors
            else:
                can_run = False

        else:
            ecn_file = ecn_upload






            bom_file = bom_upload
            can_run = can_run and bool(ecn_file and bom_file)

    else:

        manual_input = _render_manual_form()
        can_run = can_run and manual_input is not None


    if st.button("Run Checks", type="primary", disabled=not can_run):


        try:

            if mode == "Batch pre-check":

                # Rebuild the preparation here because the preview's temporary
                # files were deleted after the previous Streamlit rerun.
                temporary_paths = [
                    *[_write_upload(upload) for upload in ecn_files],
                    *[_write_upload(upload) for upload in bom_files],
                ]
                ecn_count = len(ecn_files)
                execution_preparation = build_batch_from_paths(
                    temporary_paths[:ecn_count],
                    temporary_paths[ecn_count:],
                )
                if execution_preparation.errors:
                    for error in batch_error_rows(execution_preparation):
                        st.error(f"{error['Role']}: {error['File']}: {error['Problem']}")
                    return

                progress_bar = st.progress(0, text="Starting batch pre-check...")

                def report_batch_progress(progress) -> None:
                    progress_bar.progress(
                        progress.completed / progress.total,
                        text=(
                            f"Checking {progress.completed}/{progress.total}: "
                            f"{progress.current_case_id}"
                        ),
                    )

                persistence = _start_batch_evaluation(tester_email, tester_name, execution_preparation.batch)

                if persistence is None and _evaluation_db_config().get("ECN_DB_PASSWORD"):
                    st.warning("Evaluation batch could not be started; validation will continue.")
                executor = lambda case: (
                    _execute_persisted_batch_case(case, persistence)
                    if persistence is not None
                    else _execute_batch_case(case)
                )

                with st.spinner("Running batch ECN validation checks..."):
                    batch_result = run_batch(
                        execution_preparation.batch,
                        executor,
                        progress_callback=report_batch_progress,
                    )
                _complete_batch_evaluation(persistence, batch_result.status)
                progress_bar.progress(1.0, text="Batch pre-check complete")

                st.session_state["batch_result"] = batch_result
                st.session_state.pop("packet", None)
                st.session_state.pop("email_status", None)
                return

            if mode == "Upload files":
                temporary_paths = [_write_upload(ecn_file), _write_upload(bom_file)]
            else:
                values, bom_rows = manual_input
                errors = validate_manual_input(values, bom_rows)
                if errors:
                    for error in errors:
                        st.error(error)
                    return
                temporary_paths = [
                    _write_text(manual_ecn_csv(values)),
                    _write_text(manual_bom_csv(bom_rows)),
                ]

            evaluation = _start_evaluation_precheck(tester_email, tester_name)
            if evaluation is None and _evaluation_db_config().get("ECN_DB_PASSWORD"):
                st.warning("Evaluation data could not be saved; validation will continue.")

            with st.spinner("Running ECN validation checks..."):
                packet = _run_pipeline(*temporary_paths)
                st.session_state["packet"] = packet
                st.session_state.pop("email_status", None)

            gate = packet["gate"]


            result_payload = {

                "packet": packet,
                "blocker_count": len(gate.get("blockers", [])),
                "part_issue_count": len(gate.get("part_issues", [])),
                "warning_count": len(gate.get("warnings", [])),
            }

            captured_files = []

            original_names = (

                [ecn_file.name, bom_file.name]
                if mode == "Upload files"
                else ["manual_ecn.csv", "manual_bom.csv"]
            )
            for role, path, original_name in zip(
                ("ecn", "bom"), temporary_paths, original_names
            ):
                source_path = Path(path)
                if source_path.exists():
                    captured_files.append(
                        {
                            "role": role,
                            "filename": original_name,
                            "bytes": source_path.read_bytes(),
                        }
                    )

            duration = _complete_evaluation_precheck(
                evaluation, gate["decision"], result_payload, captured_files
            )
            if evaluation is not None and duration is None:
                st.warning(
                    "Evaluation data could not be completed; validation results are still available."
                )
            if duration is not None:
                st.session_state["checking_duration_seconds"] = duration

        except Exception as exc:
            st.error(f"The input could not be processed: {exc}")
        finally:
            for path in temporary_paths:
                Path(path).unlink(missing_ok=True)

    if mode == "Batch pre-check":
        batch_result = st.session_state.get("batch_result")
        if batch_result is not None:
            _render_batch_result(batch_result)
        return


    packet = st.session_state.get("packet")
    if not packet:
        return

    gate = packet["gate"]


    decision = gate["decision"]

    if decision == "PASS":
        st.success("PASS — No gate-closing findings were identified.")
    else:
        st.error("FAIL — Resolve gate-closing findings before proceeding.")
    duration = st.session_state.get("checking_duration_seconds")
    if duration is not None:
        st.caption(f"Checking duration: {duration:.2f} seconds")

    _render_findings("Blockers", gate.get("blockers", []))
    _render_findings("Part Issues", gate.get("part_issues", []))
    _render_findings("Conflict Alerts", gate.get("conflict_alerts", []))
    _render_findings("Warnings", gate.get("warnings", []))
    _render_ai_notes(gate.get("ai_notes", {}))
    _render_tester_judgement(packet)

    st.subheader("Email validation report")

    validation_recipient = st.text_input(
        "Validation report recipient",
        key="validation_recipient_email",
        help="Enter the email address that should receive this validation report.",
    )
    st.caption("This report does not approve or reject the ECN.")
    email_status = st.session_state.get("email_status")
    if email_status and email_status.get("sent"):
        st.success(email_status["message"])
    elif st.button("Send Validation Email"):
        if not validation_recipient.strip():
            st.info("Enter an email address before sending the validation report.")
        else:
            with st.spinner("Sending validation report..."):
                result = send_validation_email(
                    packet,
                    recipient=validation_recipient.strip(),
                    secrets=_streamlit_secrets(),
                )
            st.session_state["email_status"] = result
            _record_notification_result(result, "validation_report")
            if result["sent"]:
                st.success(result["message"])
            elif result["status"] == "not_configured":
                st.warning(result["message"] + " Configure SMTP settings before sending.")
            else:
                st.error(result["message"])

    st.subheader("Notification Email")
    engineer_email = st.text_input("Engineer email", key="notification_engineer_email")
    ce_email = st.text_input("Chief Engineer email", key="notification_ce_email")
    if st.button("Send Notification Email", type="secondary"):
        if not engineer_email.strip():
            st.info("Enter an engineer email address before sending a notification.")
        elif decision == "PASS" and not ce_email.strip():
            st.info("Enter a Chief Engineer email address for a PASS notification.")
        else:
            if decision == "FAIL":
                result = send_fail_email(packet, engineer_email.strip())
            else:
                result = send_pass_email(packet, engineer_email.strip(), ce_email.strip())
            _record_notification_result(result, "gate_notification")
            recipients = ", ".join(result["recipients"])
            status = "sent" if result["sent"] else "dry run" if result["dry_run"] else "not sent"
            message = (
                f"Notification {status}. Recipients: {recipients}. "
                f"Subject: {result['subject']}. Dry run: {result['dry_run']}."
            )
            if result["sent"]:
                st.success(message)
            else:
                st.info(message)


if __name__ == "__main__":
    main()

    