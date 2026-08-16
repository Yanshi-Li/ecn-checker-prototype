"""
Stage 6: Approval Workflow
Handles ECN approve/reject decisions and notifications.
Gracefully degrades if email is unavailable.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ── Notifier (graceful degradation) ──────────────────────────────────────────
def _send_notification(to: str, subject: str, body: str) -> None:
    """
    Send an email notification.
    Logs only if email is unavailable (no SMTP configured).
    """
    try:
        import smtplib
        from email.mime.text import MIMEText
        import os

        smtp_host = os.environ.get("SMTP_HOST")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        smtp_user = os.environ.get("SMTP_USER")
        smtp_pass = os.environ.get("SMTP_PASS")

        if not smtp_host or not smtp_user:
            raise EnvironmentError("SMTP not configured.")

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to, msg.as_string())

        logger.info("Notification sent to %s — %s", to, subject)

    except Exception as exc:
        logger.warning(
            "Notification not sent to %s (%s) — logging only.", to, exc
        )
        logger.info("  Subject : %s", subject)
        logger.info("  Body    : %s", body)


# ── Decision builders ─────────────────────────────────────────────────────────
def _build_summary(packet: dict) -> str:
    """Build a plain-text summary of the ECN validation results."""
    header = packet["header"]
    validation = packet["validation"]
    rule_violations = validation.get("rule_violations", [])
    ai_flags = validation.get("ai_flags", {})
    context_flags = validation.get("context_flags", [])

    errors = [v for v in rule_violations if v["severity"] == "ERROR"]
    warnings = [v for v in rule_violations if v["severity"] == "WARNING"]

    lines = [
        f"ECN ID      : {header.get('ecn_id', 'N/A')}",
        f"Title       : {header.get('title', 'N/A')}",
        f"Author      : {header.get('author', 'N/A')}",
        f"Date        : {header.get('date', 'N/A')}",
        "",
        f"Rule Errors   : {len(errors)}",
        f"Rule Warnings : {len(warnings)}",
        f"Context Flags : {len(context_flags)}",
        f"AI Risk Level : {ai_flags.get('overall_risk', 'N/A')}",
        f"AI Quality    : {ai_flags.get('description_quality', 'N/A')}",
        "",
        "AI Recommendation:",
        f"  {ai_flags.get('recommendation', 'N/A')}",
    ]

    if errors:
        lines += ["", "Errors:"]
        for e in errors:
            lines.append(f"  [{e.get('rule_id')}] {e.get('message')}")

    if warnings:
        lines += ["", "Warnings:"]
        for w in warnings:
            lines.append(f"  [{w.get('rule_id')}] {w.get('message')}")

    if context_flags:
        lines += ["", "Context Flags:"]
        for f in context_flags:
            lines.append(f"  [{f.get('flag_type')}] {f.get('message')}")

    return "\n".join(lines)


# ── Public entry points ───────────────────────────────────────────────────────
def approve_ecn(
    packet: dict,
    coordinator_email: str,
    engineer_email: str,
) -> dict:
    """
    Approve the ECN and notify stakeholders.
    Returns updated packet with approval decision recorded.
    """
    ecn_id = packet["header"].get("ecn_id", "N/A")
    timestamp = datetime.now().isoformat(timespec="seconds")
    summary = _build_summary(packet)

    packet["approval"] = {
        "decision": "APPROVED",
        "timestamp": timestamp,
        "ecn_id": ecn_id,
    }

    logger.info("ECN %s APPROVED at %s", ecn_id, timestamp)

    _send_notification(
        to=engineer_email,
        subject=f"ECN {ecn_id} — APPROVED",
        body=f"Your ECN has been approved on {timestamp}.\n\n{summary}",
    )
    _send_notification(
        to=coordinator_email,
        subject=f"ECN {ecn_id} — APPROVED (Coordinator Copy)",
        body=f"ECN {ecn_id} was approved on {timestamp}.\n\n{summary}",
    )

    return packet


def reject_ecn(
    packet: dict,
    coordinator_email: str,
    engineer_email: str,
    reason: str = "Issues found during automated review.",
) -> dict:
    """
    Reject the ECN and notify stakeholders.
    Returns updated packet with rejection decision recorded.
    """
    ecn_id = packet["header"].get("ecn_id", "N/A")
    timestamp = datetime.now().isoformat(timespec="seconds")
    summary = _build_summary(packet)

    packet["approval"] = {
        "decision": "REJECTED",
        "timestamp": timestamp,
        "ecn_id": ecn_id,
        "reason": reason,
    }

    logger.info("ECN %s REJECTED at %s — %s", ecn_id, timestamp, reason)

    _send_notification(
        to=engineer_email,
        subject=f"ECN {ecn_id} — REJECTED",
        body=(
            f"Your ECN has been rejected on {timestamp}.\n\n"
            f"Reason: {reason}\n\n{summary}"
        ),
    )
    _send_notification(
        to=coordinator_email,
        subject=f"ECN {ecn_id} — REJECTED (Coordinator Copy)",
        body=(
            f"ECN {ecn_id} was rejected on {timestamp}.\n\n"
            f"Reason: {reason}\n\n{summary}"
        ),
    )

    return packet