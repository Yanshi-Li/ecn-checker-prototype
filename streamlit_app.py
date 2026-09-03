"""Public Streamlit interface for the ECN Checker pipeline."""

import hmac
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
STAGES = ROOT / "scripts" / "stages"
SUPPORTED_FILE_TYPES = ["csv", "xlsx", "xls", "pdf", "html", "htm", "eml"]


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


def _write_upload(uploaded_file) -> str:
    """Persist a Streamlit upload so the existing intake stage can read it."""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        temp_file.write(uploaded_file.getvalue())
        return temp_file.name


def _run_pipeline(ecn_path: str, bom_path: str) -> dict:
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
            st.dataframe(_finding_rows(findings), hide_index=True, use_container_width=True)
        else:
            st.info(f"No {title.lower()} found.")


def _render_ai_notes(ai_notes: dict) -> None:
    flags = ai_notes.get("flags", [])
    with st.expander(f"AI Notes ({len(flags)})"):
        availability = "AI response" if ai_notes.get("ai_available") else "Rule-based advisory"
        st.caption(availability)
        if ai_notes.get("recommendation"):
            st.write(ai_notes["recommendation"])
        if flags:
            st.dataframe(_finding_rows(flags), hide_index=True, use_container_width=True)
        else:
            st.info("No AI advisory flags found.")


def main() -> None:
    st.set_page_config(page_title="ECN Checker", page_icon="📋", layout="wide")
    # Password access control is temporarily disabled for local testing.
    st.title("ECN Checker")
    st.caption("Upload an Engineering Change Notice and BOM, then run the validation pipeline.")
    st.info(
        "Notifications require a separate button click after checks complete. "
        "They remain dry runs unless DRY_RUN is explicitly disabled."
    )

    upload_column, bom_column = st.columns(2)
    with upload_column:
        ecn_file = st.file_uploader(
            "Step 1 — Upload ECN file",
            type=SUPPORTED_FILE_TYPES,
            help="CSV, Excel, PDF, HTML, or EML files are supported by the intake stage.",
        )
    with bom_column:
        bom_file = st.file_uploader(
            "Step 2 — Upload BOM file",
            type=SUPPORTED_FILE_TYPES,
            help="CSV, Excel, PDF, HTML, or EML files are supported by the intake stage.",
        )

    if st.button("Run Checks", type="primary", disabled=not (ecn_file and bom_file)):
        temporary_paths = []
        try:
            temporary_paths = [_write_upload(ecn_file), _write_upload(bom_file)]
            with st.spinner("Running ECN validation checks..."):
                st.session_state["packet"] = _run_pipeline(*temporary_paths)
        except Exception as exc:
            st.error(f"The uploaded files could not be processed: {exc}")
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
