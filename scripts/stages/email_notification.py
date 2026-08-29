"""Stage 6 email-notification entry points for the v1.2 gate workflow."""

import logging
import os

logger = logging.getLogger(__name__)


def _get_config_value(key: str, default: str = "") -> str:
    """Read Streamlit secrets first, then fall back to CLI environment values."""
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is not None:
            value = st.secrets.get(key)
            if value is not None:
                return str(value).strip()
    except Exception:
        # No Streamlit runtime/secrets configured: use the CLI environment.
        pass

    return os.environ.get(key, default).strip()


def _resolve_email_config() -> dict:
    """Resolve SendGrid credentials and sender identity for Stage 6."""
    return {
        "api_key": _get_config_value("SENDGRID_API_KEY"),
        "from_email": _get_config_value("EMAIL_FROM_ADDRESS"),
    }


def _is_dry_run() -> bool:
    """Return whether notification delivery is disabled (the safe default)."""
    value = _get_config_value("DRY_RUN", "true").lower()
    return value not in {"0", "false", "no", "off"}


def _send_via_sendgrid(recipients: list[str], subject: str, body: str) -> None:
    """Send one plain-text email through SendGrid using resolved credentials."""

    config = _resolve_email_config()
    if not config["api_key"] or not config["from_email"]:
        raise RuntimeError(
            "SENDGRID_API_KEY and EMAIL_FROM_ADDRESS must be configured to send email."
        )

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError as exc:
        raise RuntimeError("The sendgrid package is required to send email.") from exc

    message = Mail(
        from_email=config["from_email"],
        to_emails=recipients,
        subject=subject,
        plain_text_content=body,
    )
    SendGridAPIClient(config["api_key"]).send(message)


def _deliver_notification(recipients: list[str], subject: str, body: str) -> dict:
    """Log a dry run or deliver a rendered notification through SendGrid."""
    result = {
        "sent": False,
        "recipients": recipients,
        "subject": subject,
        "body": body,
        "dry_run": _is_dry_run(),
    }
    if result["dry_run"]:
        logger.info(
            "Email dry run — recipients: %s\nSubject: %s\nBody:\n%s",
            ", ".join(recipients),
            subject,
            body,
        )
        return result

    try:
        _send_via_sendgrid(recipients, subject, body)
    except Exception as exc:
        logger.exception("SendGrid notification failed for %s", ", ".join(recipients))
        result["error"] = str(exc)
        return result

    result["sent"] = True
    logger.info("SendGrid notification sent to %s — %s", ", ".join(recipients), subject)
    return result


def _ecn_id(packet: dict) -> str:
    """Return an ECN identifier without requiring optional packet fields."""
    return packet.get("header", {}).get("ecn_id", "N/A")


def _format_fail_findings(findings: list[dict]) -> list[str]:
    """Format gate findings with their rule/flag and affected part where present."""
    if not findings:
        return ["- None."]

    lines = []
    for finding in findings:
        label = finding.get("rule_id") or finding.get("flag_type")
        part_number = finding.get("part_number")
        context = " ".join(
            value for value in (f"[{label}]" if label else "", part_number or "") if value
        )
        message = finding.get("message", "No details provided.")
        lines.append(f"- {context}: {message}" if context else f"- {message}")
    return lines


def _build_fail_body(packet: dict) -> str:
    """Render the Node 6a action-required notification body."""
    gate = packet.get("gate", {})
    sections = [
        f"ECN {_ecn_id(packet)} did not pass the validation gate.",
        "",
        "❌ Blockers",
        *_format_fail_findings(gate.get("blockers", [])),
        "",
        "❌ Part Issues",
        *_format_fail_findings(gate.get("part_issues", [])),
        "",
        "❌ Conflicts",
        *_format_fail_findings(gate.get("conflict_alerts", [])),
        "",
        "Please fix the issues above and resubmit this ECN for validation.",
    ]
    return "\n".join(sections)


def send_fail_email(packet: dict, engineer_email: str) -> dict:
    """Send or dry-run the Node 6a notification for a failed ECN gate."""
    return _deliver_notification(
        recipients=[engineer_email],
        subject=f"[{_ecn_id(packet)}] Action Required — Fix and Resubmit",
        body=_build_fail_body(packet),
    )



def _format_ai_notes(ai_notes: dict) -> list[str]:
    """Format advisory AI output without representing it as a gate blocker."""
    lines = [
        f"- AI analysis available: {'Yes' if ai_notes.get('ai_available') else 'No'}.",
        f"- Mismatch flag: {'Yes' if ai_notes.get('mismatch_flag') else 'No'}.",
    ]
    flags = ai_notes.get("flags", [])
    if flags:
        for flag in flags:
            if not isinstance(flag, dict):
                lines.append(f"- {flag}")
                continue
            flag_type = flag.get("type", "AI_NOTE")
            detail = flag.get("detail", "No details provided.")
            lines.append(f"- [{flag_type}] {detail}")
    else:
        lines.append("- No AI flags.")

    recommendation = ai_notes.get("recommendation") or "No recommendation provided."
    confidence = ai_notes.get("confidence")
    lines.extend(
        [
            f"- Recommendation: {recommendation}",
            f"- Confidence: {confidence if confidence is not None else 'N/A'}",
        ]
    )
    return lines


def _build_pass_body(packet: dict) -> str:
    """Render the Node 6b CE-review notification body."""
    gate = packet.get("gate", {})
    ai_notes = gate.get("ai_notes", {})
    if not isinstance(ai_notes, dict):
        ai_notes = {}

    sections = [
        f"ECN {_ecn_id(packet)} passed the validation gate and is ready for Chief Engineer review.",
        "",
        "⚠️ Warnings (advisory only)",
        *_format_fail_findings(gate.get("warnings", [])),
        "",
        "🤖 AI Notes (advisory only)",
        *_format_ai_notes(ai_notes),
    ]
    return "\n".join(sections)


def send_pass_email(packet: dict, engineer_email: str, ce_email: str) -> dict:
    """Send or dry-run the Node 6b notification for an ECN ready for CE review."""
    return _deliver_notification(
        recipients=[engineer_email, ce_email],
        subject=f"[{_ecn_id(packet)}] Gate Passed — Ready for CE Review",
        body=_build_pass_body(packet),
    )