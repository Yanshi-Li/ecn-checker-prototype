"""Public Streamlit interface for the ECN Checker pipeline."""

import csv
import datetime as dt
import importlib.util
import io
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

# Stages dynamically loaded below import the shared rule_catalogue module from
# scripts/. Make that directory importable in both Streamlit and test sessions.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scripts.batch_intake import BatchPreparation, build_batch_from_paths  # noqa: E402
from scripts.batch_orchestration import BatchCase, BatchResult, run_batch  # noqa: E402

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
    start_precheck,
    store_evaluation_files,

    update_precheck_case_status,
)



def _load(name: str):
    """Load a stage by file path to avoid package-name shadowing."""
    path = STAGES / f"{name}.py"
    module_name = f"ecn_checker_stage_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load pipeline stage: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


intake_mod = _load("intake")
rule_engine_mod = _load("rule_engine")
ai_advisory_mod = _load("ai_advisory")
context_engine_mod = _load("context_engine")
merge_step_mod = _load("merge_step")
validation_notification_mod = _load("validation_notification")
email_notification_mod = _load("email_notification")

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
        files = []

        for role, source in (("ecn", case.logical_ecn.metadata.get("source_file")), ("bom", case.bom.metadata.get("source_file") if case.bom else None)):
            if source and Path(str(source)).exists():
                source_path = Path(str(source))
                files.append({"role": role, "filename": source_path.name, "bytes": source_path.read_bytes()})
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


def _finding_rows(findings: list[dict]) -> list[dict]:
    """Convert gate findings to the concise table shape used by the UI."""
    return [
        {
            "Finding": finding.get("rule_id")
            or finding.get("flag_type")
            or finding.get("type", "—"),
            "Severity": finding.get("severity", "ADVISORY"),
            "Message": finding.get("message") or finding.get("detail", ""),
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
            return complete_precheck(
                connection, attempt_id, session_id, system_decision, result_payload
            )
    except Exception:
        return None


def main() -> None:
    st.set_page_config(page_title="ECN Checker", page_icon="📋", layout="wide")
    # Password access control is temporarily disabled for local testing.
    st.title("ECN Checker")

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


            for role, path in zip(("ecn", "bom"), temporary_paths):
                source_path = Path(path)
                if source_path.exists():
                    captured_files.append({"role": role, "filename": source_path.name, "bytes": source_path.read_bytes()})
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

    st.divider()
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
                result = send_pass_email(
                    packet,
                    engineer_email.strip(),
                    ce_email.strip(),
                )

            recipients = ", ".join(result["recipients"])
            status = (
                "sent"
                if result["sent"]
                else "dry run"
                if result["dry_run"]
                else "not sent"
            )
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
    