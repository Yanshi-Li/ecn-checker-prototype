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

send_validation_email = validation_notification_mod.send_validation_email
DEFAULT_RECIPIENT = validation_notification_mod.DEFAULT_RECIPIENT


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
    row = {field: "" if values.get(field) is None else str(values.get(field)) for field in ECN_MANUAL_FIELDS}
    return _csv_text([row], ECN_MANUAL_FIELDS)


def manual_bom_csv(rows: list[dict[str, object]]) -> str:
    """Serialize canonical manual BOM rows for the existing loader."""
    normalized = []
    for index, row in enumerate(rows, start=1):
        normalized.append({
            "line_number": row.get("line_number") or index,
            "part_number": row.get("part_number", ""),
            "description": row.get("description", ""),
            "quantity": row.get("quantity", "1"),
            "unit": row.get("unit", "EA"),
            "action": row.get("action", ""),
            "parent_part_no": row.get("parent_part_no", ""),
        })
    return _csv_text(normalized, BOM_MANUAL_FIELDS)


def validate_manual_input(values: dict[str, object], bom_rows: list[dict[str, object]]) -> list[str]:
    """Return user-facing errors before invoking the authoritative pipeline."""
    errors = [f"{field.replace('_', ' ').title()} is required." for field in intake_mod.REQUIRED_ECN_FIELDS if not str(values.get(field, "")).strip()]
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
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", suffix=suffix, delete=False) as temp_file:
        temp_file.write(text)
        return temp_file.name


def _write_upload(uploaded_file) -> str:
    """Persist a Streamlit upload so the existing intake stage can read it."""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        temp_file.write(uploaded_file.getvalue())
        return temp_file.name


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
            "Finding": finding.get("rule_id") or finding.get("flag_type") or finding.get("type", "—"),
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
        values[field] = st.text_area(label, key=f"manual_{field}") if field in {"reason_for_change", "description_of_change", "products_affected", "change_actions"} else st.text_input(label, key=f"manual_{field}")
    date_value = st.date_input("Date", value=None, key="manual_date")
    values["date"] = date_value.isoformat() if isinstance(date_value, (dt.date, dt.datetime)) else ""

    with st.expander("Optional canonical fields"):
        optional = {
            "project": "Project", "product_group": "Product Group", "change_category": "Change Category",
            "associated_a3": "Associated A3", "a3_number": "A3 Number", "checker": "Checker",
            "reviewer": "Reviewer", "chief_engineer": "Chief Engineer", "bom_coordinator": "BOM Coordinator",
        }
        for field, label in optional.items():
            values[field] = st.text_input(label, key=f"manual_{field}")

    st.subheader("BOM lines")
    default_rows = pd.DataFrame([{
        "line_number": 1, "part_number": "", "description": "", "quantity": "1",
        "unit": "EA", "action": "", "parent_part_no": "",
    }])
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


def main() -> None:
    st.set_page_config(page_title="ECN Checker", page_icon="📋", layout="wide")
    # Password access control is temporarily disabled for local testing.
    st.title("ECN Checker")


    mode = st.radio("Input method", ["Upload files", "Manual intake"], horizontal=True, key="input_mode")
    temporary_paths: list[str] = []
    can_run = False
    if mode == "Upload files":
        upload_column, bom_column = st.columns(2)
        with upload_column:
            ecn_file = st.file_uploader(
                "Step 1 — Upload ECN file",
                type=ECN_FILE_TYPES,
                help="CSV, Excel, PDF, HTML, or EML files are supported by the intake stage.",
            )
        with bom_column:
            bom_file = st.file_uploader(
                "Step 2 — Upload BOM file",
                type=BOM_FILE_TYPES,
                help="CSV, Excel, or PDF files are supported by the intake stage.",
            )
        can_run = bool(ecn_file and bom_file)
    else:
        manual_input = _render_manual_form()
        can_run = manual_input is not None

    if st.button("Run Checks", type="primary", disabled=not can_run):
        try:
            if mode == "Upload files":
                temporary_paths = [_write_upload(ecn_file), _write_upload(bom_file)]
            else:
                values, bom_rows = manual_input
                errors = validate_manual_input(values, bom_rows)
                if errors:
                    for error in errors:
                        st.error(error)
                    return
                temporary_paths = [_write_text(manual_ecn_csv(values)), _write_text(manual_bom_csv(bom_rows))]
            with st.spinner("Running ECN validation checks..."):
                st.session_state["packet"] = _run_pipeline(*temporary_paths)
                st.session_state.pop("email_status", None)
        except Exception as exc:
            st.error(f"The input could not be processed: {exc}")
        finally:
            for path in temporary_paths:
                Path(path).unlink(missing_ok=True)

    packet = st.session_state.get("packet")
    if not packet:
        return

    gate = packet["gate"]
    decision = gate["decision"]
    if decision == "PASS":
        st.success("PASS — No gate-closing findings were identified.")
    else:
        st.error("FAIL — Resolve gate-closing findings before proceeding.")

    _render_findings("Blockers", gate.get("blockers", []))
    _render_findings("Part Issues", gate.get("part_issues", []))
    _render_findings("Conflict Alerts", gate.get("conflict_alerts", []))
    _render_findings("Warnings", gate.get("warnings", []))
    _render_ai_notes(gate.get("ai_notes", {}))

    st.divider()
    st.subheader("Email validation report")
    st.caption(f"The report will be sent to {DEFAULT_RECIPIENT}. This does not approve or reject the ECN.")
    email_status = st.session_state.get("email_status")
    if email_status and email_status.get("sent"):
        st.success(email_status["message"])
    elif st.button("Send Validation Email"):
        with st.spinner("Sending validation report..."):
            result = send_validation_email(packet, secrets=_streamlit_secrets())
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
                    packet, engineer_email.strip(), ce_email.strip()
                )

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












