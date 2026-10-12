"""Minimal validation email content and Proofpoint HTTP delivery."""

from __future__ import annotations

import logging
import os
from typing import Mapping
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)
PROOFPOINT_TOKEN_URL = "https://mail-us.ser.proofpoint.com/v1/token"
INTERNAL_EMAIL_DOMAIN = "fisherpaykel.com"


def _all_findings(packet: dict) -> list[dict]:
    gate = packet.get("gate", {})
    return [finding for group in ("blockers", "part_issues", "conflict_alerts", "warnings") for finding in gate.get(group, [])]


def _safe_line(value: object, limit: int = 120) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_validation_email(packet: dict, app_url: str = "") -> tuple[str, str]:
    """Build a minimal report containing only the ECN, decision, and rule summary."""
    header = packet.get("header", {})
    gate = packet.get("gate", {})
    decision = _safe_line(gate.get("decision", "UNKNOWN")).upper()

    notice = _safe_line(header.get("change_notice_number") or header.get("ecn_id") or "N/A") or "N/A"
    findings = _all_findings(packet)
    lines = [f"ECN: {notice}", f"Decision: {decision}", f"Rule findings: {len(findings)}"]
    lines.extend(
        f"- {_safe_line(finding.get('rule_id') or finding.get('finding_id') or finding.get('flag_type') or 'Finding')}: "
        f"{_safe_line(finding.get('severity', 'ADVISORY'))}"
        for finding in findings
    )

    parsed = urlparse(app_url.strip()) if app_url else None
    if parsed and parsed.scheme in {"http", "https"} and parsed.netloc and not (
        parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        lines.extend(["", f"Open the ECN Checker: {app_url.strip().rstrip('/')}"])
    subject = f"ECN Check — {notice} — {decision}"
    return subject, "\n".join(lines)


def _configuration(environment: Mapping[str, str]) -> dict[str, str]:
    keys = (
        "PROOFPOINT_SEND_URL", "PROOFPOINT_SENDER_ADDRESS", "PROOFPOINT_CLIENT_ID",
        "PROOFPOINT_CLIENT_SECRET", "PROOFPOINT_TOKEN_GRANT_TYPE", "PROOFPOINT_TOKEN_SCOPE",
        "PROOFPOINT_TOKEN_AUDIENCE", "PROOFPOINT_TOKEN_RESPONSE_FIELD",
        "PROOFPOINT_TOKEN_CLIENT_ID_FIELD", "PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD",
        "PROOFPOINT_TOKEN_GRANT_TYPE_FIELD", "PROOFPOINT_TOKEN_SCOPE_FIELD",
        "PROOFPOINT_TOKEN_AUDIENCE_FIELD", "PROOFPOINT_SEND_FROM_FIELD",
        "PROOFPOINT_SEND_TO_FIELD", "PROOFPOINT_SEND_SUBJECT_FIELD", "PROOFPOINT_SEND_BODY_FIELD",
        "PROOFPOINT_TOKEN_REQUEST_FORMAT", "PROOFPOINT_SEND_REQUEST_FORMAT", "ECN_APP_URL",
    )
    return {key: str(environment.get(key, "")).strip() for key in keys}





def _internal_recipient(recipient: str) -> bool:
    value = recipient.strip().casefold()
    local, separator, domain = value.rpartition("@")
    return bool(separator and local and domain == INTERNAL_EMAIL_DOMAIN)


def send_validation_email(
    packet: dict,
    recipient: str,
    environ: Mapping[str, str] | None = None,
    http_post=None,
) -> dict[str, object]:
    """Send through the configured Proofpoint contract; never expose provider details."""
    environment = environ if environ is not None else os.environ
    settings = _configuration(environment)
    if not _internal_recipient(recipient):
        return {"sent": False, "status": "failed", "message": "Recipient must be an internal Fisher & Paykel address."}

    required = (
        "PROOFPOINT_SEND_URL", "PROOFPOINT_SENDER_ADDRESS", "PROOFPOINT_CLIENT_ID",
        "PROOFPOINT_CLIENT_SECRET", "PROOFPOINT_TOKEN_GRANT_TYPE",
        "PROOFPOINT_TOKEN_RESPONSE_FIELD", "PROOFPOINT_TOKEN_CLIENT_ID_FIELD",
        "PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD", "PROOFPOINT_TOKEN_GRANT_TYPE_FIELD",
        "PROOFPOINT_SEND_FROM_FIELD", "PROOFPOINT_SEND_TO_FIELD",
        "PROOFPOINT_SEND_SUBJECT_FIELD", "PROOFPOINT_SEND_BODY_FIELD",
    )
    if (not settings["PROOFPOINT_TOKEN_SCOPE"] and not settings["PROOFPOINT_TOKEN_AUDIENCE"]) or any(
        not settings[key] for key in required
    ):
        return {"sent": False, "status": "not_configured", "message": "Proofpoint delivery is not configured."}

    token_url = environment.get("PROOFPOINT_TOKEN_URL", PROOFPOINT_TOKEN_URL).strip()
    token_endpoint = urlparse(token_url)
    send_endpoint = urlparse(settings["PROOFPOINT_SEND_URL"])
    if any(
        endpoint.scheme != "https" or not endpoint.netloc
        or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
        for endpoint in (token_endpoint, send_endpoint)
    ) or not _internal_recipient(settings["PROOFPOINT_SENDER_ADDRESS"]):
        return {"sent": False, "status": "not_configured", "message": "Proofpoint delivery is not configured."}

    token_format = settings["PROOFPOINT_TOKEN_REQUEST_FORMAT"].lower()
    send_format = settings["PROOFPOINT_SEND_REQUEST_FORMAT"].lower()
    if token_format not in {"json", "form"} or send_format not in {"json", "form"}:
        return {"sent": False, "status": "not_configured", "message": "Proofpoint delivery is not configured."}
    if settings["PROOFPOINT_TOKEN_SCOPE"] and not settings["PROOFPOINT_TOKEN_SCOPE_FIELD"]:
        return {"sent": False, "status": "not_configured", "message": "Proofpoint delivery is not configured."}
    if settings["PROOFPOINT_TOKEN_AUDIENCE"] and not settings["PROOFPOINT_TOKEN_AUDIENCE_FIELD"]:
        return {"sent": False, "status": "not_configured", "message": "Proofpoint delivery is not configured."}

    token_fields = {
        settings["PROOFPOINT_TOKEN_CLIENT_ID_FIELD"]: settings["PROOFPOINT_CLIENT_ID"],
        settings["PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD"]: settings["PROOFPOINT_CLIENT_SECRET"],
        settings["PROOFPOINT_TOKEN_GRANT_TYPE_FIELD"]: settings["PROOFPOINT_TOKEN_GRANT_TYPE"],
    }
    if settings["PROOFPOINT_TOKEN_SCOPE"]:
        token_fields[settings["PROOFPOINT_TOKEN_SCOPE_FIELD"]] = settings["PROOFPOINT_TOKEN_SCOPE"]
    if settings["PROOFPOINT_TOKEN_AUDIENCE"]:
        token_fields[settings["PROOFPOINT_TOKEN_AUDIENCE_FIELD"]] = settings["PROOFPOINT_TOKEN_AUDIENCE"]

    subject, body = build_validation_email(packet, settings["ECN_APP_URL"])
    send_fields = {
        settings["PROOFPOINT_SEND_FROM_FIELD"]: settings["PROOFPOINT_SENDER_ADDRESS"],
        settings["PROOFPOINT_SEND_TO_FIELD"]: recipient.strip(),
        settings["PROOFPOINT_SEND_SUBJECT_FIELD"]: subject,
        settings["PROOFPOINT_SEND_BODY_FIELD"]: body,
    }
    post = http_post or httpx.post
    try:
        token_response = post(token_url, **{token_format: token_fields, "timeout": 10})
        token_response.raise_for_status()
        access_token = token_response.json().get(settings["PROOFPOINT_TOKEN_RESPONSE_FIELD"])
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("missing access token")
        delivery_response = post(
            settings["PROOFPOINT_SEND_URL"],
            **{send_format: send_fields, "headers": {"Authorization": f"Bearer {access_token}"}, "timeout": 10},
        )
        delivery_response.raise_for_status()
    except Exception as exc:
        logger.error("Proofpoint delivery failed (%s)", type(exc).__name__)
        return {"sent": False, "status": "failed", "message": "Email could not be sent."}

    return {"sent": True, "status": "sent", "message": "Validation result notification sent."}