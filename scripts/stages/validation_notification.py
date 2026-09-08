"""Validation-report email creation and delivery."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText
from typing import Mapping

logger = logging.getLogger(__name__)

DEFAULT_RECIPIENT = "yanshili645@gmail.com"
SMTP_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS")



def _value(source: Mapping[str, object] | None, key: str) -> str:
    if not source:
        return ""
    value = source.get(key, "")
    return "" if value is None else str(value)


def smtp_settings(
    secrets: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return Streamlit-secret values with environment fallback."""
    environment = environ if environ is not None else os.environ
    settings = {}
    for key in SMTP_KEYS:
        settings[key] = _value(secrets, key) or str(environment.get(key, ""))
    settings["SMTP_PORT"] = settings["SMTP_PORT"] or "587"
    return settings


def _all_findings(packet: dict) -> list[dict]:
    gate = packet.get("gate", {})
    groups = ("blockers", "part_issues", "conflict_alerts", "warnings")
    return [finding for group in groups for finding in gate.get(group, [])]


def build_validation_email(packet: dict) -> tuple[str, str]:
    """Build a validation-only subject and plain-text report body."""
    header = packet.get("header", {})
    gate = packet.get("gate", {})
    decision = gate.get("decision", "UNKNOWN")
    notice = header.get("change_notice_number") or header.get("ecn_id") or "N/A"
    subject = f"ECN Validation Report — {notice} — {decision}"

    lines = [
        "ECN Validation Report",
        "=====================",
        f"Change Notice Number: {notice}",
        f"Name of Change: {header.get('name_of_change') or header.get('title') or 'N/A'}",
        f"Date: {header.get('date') or 'N/A'}",
        f"Products Affected: {header.get('products_affected') or header.get('affected_parts') or 'N/A'}",
        f"Overall Decision: {decision}",
        f"Blockers: {len(gate.get('blockers', []))}",
        f"Part Issues: {len(gate.get('part_issues', []))}",
        f"Conflict Alerts: {len(gate.get('conflict_alerts', []))}",
        f"Warnings: {len(gate.get('warnings', []))}",
        "",
        "This is an automated validation report. It is not an approval or rejection decision.",
    ]

    ai_notes = gate.get("ai_notes", {})
    if ai_notes.get("recommendation"):
        lines.extend(["", "AI Recommendation:", str(ai_notes["recommendation"])])

    findings = _all_findings(packet)
    if findings:
        lines.extend(["", "Findings:"])
        for finding in findings:
            identifier = finding.get("rule_id") or finding.get("finding_id") or finding.get("flag_type") or "finding"
            lines.append(
                f"- [{identifier}] {finding.get('severity', 'ADVISORY')} "
                f"{finding.get('message') or finding.get('detail', '')}"
            )
            for field in ("gate_effect", "location", "evidence"):
                if finding.get(field) not in (None, "", []):
                    lines.append(f"  {field.replace('_', ' ').title()}: {finding[field]}")
    else:
        lines.extend(["", "Findings:", "- No gate findings were identified."])

    return subject, "\n".join(lines)


def send_validation_email(
    packet: dict,
    recipient: str = DEFAULT_RECIPIENT,
    secrets: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
    smtp_factory=smtplib.SMTP,
) -> dict[str, object]:
    """Send a validation report and return a UI-safe result."""
    settings = smtp_settings(secrets=secrets, environ=environ)
    if not settings["SMTP_HOST"] or not settings["SMTP_USER"]:
        return {"sent": False, "status": "not_configured", "message": "SMTP is not configured."}

    subject, body = build_validation_email(packet)
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = settings["SMTP_USER"]
    message["To"] = recipient

    phase = "connect"
    try:
        with smtp_factory(settings["SMTP_HOST"], int(settings["SMTP_PORT"])) as server:
            phase = "starttls"
            server.starttls()
            phase = "login"
            server.login(settings["SMTP_USER"], settings["SMTP_PASS"])
            phase = "sendmail"
            server.sendmail(settings["SMTP_USER"], [recipient], message.as_string())
    except Exception as exc:
        # Never log SMTP credentials, addresses, or exception text: provider
        # errors can echo request data. The exception type and phase are enough
        # to distinguish connection, TLS, authentication, and delivery errors.
        logger.error(
            "SMTP delivery failed during %s (%s) to %s:%s",
            phase,
            type(exc).__name__,
            settings["SMTP_HOST"],
            settings["SMTP_PORT"],
        )
        return {"sent": False, "status": "failed", "message": "Email could not be sent."}

    return {"sent": True, "status": "sent", "message": f"Validation report sent to {recipient}."}