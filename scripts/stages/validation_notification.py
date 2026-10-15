"""Minimal validation email content and Proofpoint SER HTTP delivery."""

from __future__ import annotations

import logging
import os
import ssl
import time
from typing import Any, Mapping

from urllib.parse import urlparse

import httpx
import truststore

logger = logging.getLogger(__name__)

PROOFPOINT_TOKEN_URL = "https://mail-us.ser.proofpoint.com/v1/token"
PROOFPOINT_SEND_URL = "https://mail-us.ser.proofpoint.com/v1/send"
INTERNAL_EMAIL_DOMAIN = "fisherpaykel.com"

# Windows / macOS: use OS trust store (Zscaler root). Linux containers: fall back
# to SSL_CERT_FILE / REQUESTS_CA_BUNDLE / PROOFPOINT_CA_BUNDLE if set.
def _ssl_verify() -> ssl.SSLContext | str | bool:
    ca_bundle = (
        os.environ.get("PROOFPOINT_CA_BUNDLE", "").strip()
        or os.environ.get("SSL_CERT_FILE", "").strip()
        or os.environ.get("REQUESTS_CA_BUNDLE", "").strip()
    )
    if ca_bundle and os.path.isfile(ca_bundle):
        return ca_bundle
    try:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        logger.warning("truststore SSLContext unavailable; using default verify")
        return True


_SSL_VERIFY = _ssl_verify()

# Process-local token cache (SER tokens last ~4 hours).
_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def _all_findings(packet: dict) -> list[dict]:
    gate = packet.get("gate", {})
    return [
        finding
        for group in ("blockers", "part_issues", "conflict_alerts", "warnings")
        for finding in gate.get(group, [])
    ]


def _safe_line(value: object, limit: int = 120) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_reviewer_task_reminder(packet: dict, app_url: str = "") -> tuple[str, str]:
    """Build a reminder that an ECN review task is assigned, without result details."""
    header = packet.get("header", {})
    notice = _safe_line(header.get("change_notice_number") or header.get("ecn_id") or "N/A") or "N/A"
    lines = [
        f"ECN: {notice}",
                "A review task has been assigned to you in the ECN Checker.",
        "Sign in to the ECN Checker to open the assigned review.",

    ]
    parsed = urlparse(app_url.strip()) if app_url else None
    if parsed and parsed.scheme in {"http", "https"} and parsed.netloc and not (

        parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        lines.extend(["", f"Open the ECN Checker: {app_url.strip().rstrip('/')} "])
    return f"ECN review task assigned — {notice}", "\n".join(lines)




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
        "PROOFPOINT_TOKEN_URL",
        "PROOFPOINT_SEND_URL",
        "PROOFPOINT_SENDER_ADDRESS",
        "PROOFPOINT_CLIENT_ID",
        "PROOFPOINT_CLIENT_SECRET",
        "PROOFPOINT_TOKEN_GRANT_TYPE",
        "PROOFPOINT_TOKEN_SCOPE",
        "PROOFPOINT_TOKEN_AUDIENCE",
        "PROOFPOINT_TOKEN_RESPONSE_FIELD",
        "PROOFPOINT_TOKEN_CLIENT_ID_FIELD",
        "PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD",
        "PROOFPOINT_TOKEN_GRANT_TYPE_FIELD",
        "PROOFPOINT_TOKEN_SCOPE_FIELD",
        "PROOFPOINT_TOKEN_AUDIENCE_FIELD",
        "PROOFPOINT_TOKEN_REQUEST_FORMAT",
        "PROOFPOINT_SEND_REQUEST_FORMAT",
        "PROOFPOINT_HEADER_FROM_EMAIL",
        "ECN_APP_URL",
    )
    return {key: str(environment.get(key, "")).strip() for key in keys}


def _internal_recipient(recipient: str) -> bool:
    value = recipient.strip().casefold()
    local, separator, domain = value.rpartition("@")
    return bool(separator and local and domain == INTERNAL_EMAIL_DOMAIN)


def _https_endpoint_ok(url: str) -> bool:
    endpoint = urlparse(url)
    return (
        endpoint.scheme == "https"
        and bool(endpoint.netloc)
        and not endpoint.username
        and not endpoint.password
        and not endpoint.query
        and not endpoint.fragment
    )


def _build_ser_send_payload(
    *,
    sender: str,
    header_from: str,
    recipients: list[str],
    subject: str,
    body: str,
) -> dict:
    """Build the Secure Email Relay /v1/send JSON payload."""
    return {
        "from": {"email": sender},
        "headers": {"from": {"email": header_from}},
        "tos": [{"email": recipient} for recipient in recipients],
        "subject": subject,
        "content": [{"type": "text/plain", "body": body}],
    }



def _httpx_body_kwargs(fmt: str, body: dict) -> dict[str, object]:
    key = (fmt or "").lower().strip()
    if key == "form":
        return {"data": body}
    if key == "json":
        return {"json": body}
    raise ValueError(f"unsupported request format: {fmt}")


def _fetch_access_token(
    *,
    token_url: str,
    token_format: str,
    token_fields: dict[str, str],
    response_field: str,
    post,
) -> str:
    now = time.time()
    cached = _token_cache.get("access_token")
    expires_at = float(_token_cache.get("expires_at") or 0.0)
    if isinstance(cached, str) and cached and now < (expires_at - 300):
        return cached

    token_response = post(
        token_url,
        **_httpx_body_kwargs(token_format, token_fields),
        timeout=10,
        verify=_SSL_VERIFY,
    )
    token_response.raise_for_status()
    payload = token_response.json()
    access_token = payload.get(response_field)
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("missing access token")

    expires_in = payload.get("expires_in", 14400)
    try:
        expires_in_s = float(expires_in)
    except (TypeError, ValueError):
        expires_in_s = 14400.0

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = now + expires_in_s
    return access_token


def send_validation_email(
    packet: dict,
    recipient: str,
    environ: Mapping[str, str] | None = None,
    http_post=None,
) -> dict[str, object]:
    """Send a saved validation result through Proofpoint SER."""
    return _send_email(packet, recipient, build_validation_email, environ, http_post)


def send_reviewer_task_reminder(
    packet: dict,
    recipient: str,
    environ: Mapping[str, str] | None = None,
    http_post=None,
) -> dict[str, object]:
    """Send an assignment reminder without exposing validation result details."""
    return _send_email(packet, recipient, build_reviewer_task_reminder, environ, http_post)


def send_email_content(
    recipients: list[str],
    subject: str,
    body: str,
    environ: Mapping[str, str] | None = None,
    http_post=None,
) -> dict[str, object]:
    """Send plain-text content to internal recipients through Secure Email Relay."""
    environment = environ if environ is not None else os.environ
    settings = _configuration(environment)
    normalized_recipients = [recipient.strip() for recipient in recipients]
    if not normalized_recipients or any(
        not _internal_recipient(recipient) for recipient in normalized_recipients
    ):
        return {
            "sent": False,
            "status": "failed",
            "message": "Recipients must be internal Fisher & Paykel addresses.",
        }

    # SER does not require scope/audience.
    required = (
        "PROOFPOINT_SEND_URL",
        "PROOFPOINT_SENDER_ADDRESS",
        "PROOFPOINT_CLIENT_ID",
        "PROOFPOINT_CLIENT_SECRET",
        "PROOFPOINT_TOKEN_GRANT_TYPE",
        "PROOFPOINT_TOKEN_RESPONSE_FIELD",
        "PROOFPOINT_TOKEN_CLIENT_ID_FIELD",
        "PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD",
        "PROOFPOINT_TOKEN_GRANT_TYPE_FIELD",
        "PROOFPOINT_TOKEN_REQUEST_FORMAT",
        "PROOFPOINT_SEND_REQUEST_FORMAT",
    )
    if any(not settings[key] for key in required):
        return {
            "sent": False,
            "status": "not_configured",
            "message": "Secure Email Relay delivery is not configured.",
        }
    if settings["PROOFPOINT_TOKEN_SCOPE"] and not settings["PROOFPOINT_TOKEN_SCOPE_FIELD"]:
        return {
            "sent": False,
            "status": "not_configured",
            "message": "Secure Email Relay delivery is not configured.",
        }
    if settings["PROOFPOINT_TOKEN_AUDIENCE"] and not settings["PROOFPOINT_TOKEN_AUDIENCE_FIELD"]:
        return {
            "sent": False,
            "status": "not_configured",
            "message": "Secure Email Relay delivery is not configured.",
        }

    token_url = settings["PROOFPOINT_TOKEN_URL"] or PROOFPOINT_TOKEN_URL
    send_url = settings["PROOFPOINT_SEND_URL"] or PROOFPOINT_SEND_URL
    header_from = settings["PROOFPOINT_HEADER_FROM_EMAIL"] or settings["PROOFPOINT_SENDER_ADDRESS"]
    if (
        not _https_endpoint_ok(token_url)
        or not _https_endpoint_ok(send_url)
        or not _internal_recipient(settings["PROOFPOINT_SENDER_ADDRESS"])
        or not _internal_recipient(header_from)
    ):
        return {
            "sent": False,
            "status": "not_configured",
            "message": "Secure Email Relay delivery is not configured.",
        }

        
    

    token_fields = {
        settings["PROOFPOINT_TOKEN_CLIENT_ID_FIELD"]: settings["PROOFPOINT_CLIENT_ID"],
        settings["PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD"]: settings["PROOFPOINT_CLIENT_SECRET"],
        settings["PROOFPOINT_TOKEN_GRANT_TYPE_FIELD"]: settings["PROOFPOINT_TOKEN_GRANT_TYPE"],
    }
    if settings["PROOFPOINT_TOKEN_SCOPE"]:
        token_fields[settings["PROOFPOINT_TOKEN_SCOPE_FIELD"]] = settings["PROOFPOINT_TOKEN_SCOPE"]
    if settings["PROOFPOINT_TOKEN_AUDIENCE"]:
        token_fields[settings["PROOFPOINT_TOKEN_AUDIENCE_FIELD"]] = settings["PROOFPOINT_TOKEN_AUDIENCE"]

    send_payload = _build_ser_send_payload(
        sender=settings["PROOFPOINT_SENDER_ADDRESS"],
        header_from=header_from,
        recipients=normalized_recipients,
        subject=subject,
        body=body,
    )
    post = http_post or httpx.post
    try:
        access_token = _fetch_access_token(
            token_url=token_url,
                        token_format=settings["PROOFPOINT_TOKEN_REQUEST_FORMAT"].lower(),

            token_fields=token_fields,
            response_field=settings["PROOFPOINT_TOKEN_RESPONSE_FIELD"],
            post=post,
        )
        response = post(
            send_url,
            json=send_payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=10,
            verify=_SSL_VERIFY,
        )
        response.raise_for_status()
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 401:
            _token_cache["access_token"] = None
            _token_cache["expires_at"] = 0.0
        logger.error("Secure Email Relay delivery failed (%s)", type(exc).__name__)
        return {"sent": False, "status": "failed", "message": "Email could not be sent."}

    return {"sent": True, "status": "sent", "message": "Email sent."}


def _send_email(
    packet: dict,
    recipient: str,
    content_builder,
    environ: Mapping[str, str] | None = None,
    http_post=None,
) -> dict[str, object]:
    environment = environ if environ is not None else os.environ
    subject, body = content_builder(packet, _configuration(environment)["ECN_APP_URL"])
    result = send_email_content([recipient], subject, body, environment, http_post)
    if result.get("sent"):
        result["message"] = (
            "Validation result notification sent."
            if content_builder is build_validation_email
            else "Reviewer task reminder sent."
        )
    return result