from scripts.stages.validation_notification import build_validation_email, send_validation_email


PACKET = {
    "header": {"change_notice_number": "ECN-1234567", "name_of_change": "Sensitive title"},
    "gate": {
        "decision": "FAIL",
        "blockers": [{"rule_id": "H01", "severity": "ERROR", "message": "Reason is missing.", "evidence": "private evidence"}],
        "part_issues": [],
        "conflict_alerts": [],
        "warnings": [],
        "ai_notes": {"recommendation": "private recommendation"},
    },
}


def test_validation_email_contains_only_ec_identifier_decision_and_rule_summary():
    subject, body = build_validation_email(PACKET)

    assert "ECN-1234567" in subject
    assert "FAIL" in subject
    assert "H01" in body
    assert "ERROR" in body
    assert "Reason is missing." not in body
    assert "private evidence" not in body
    assert "Sensitive title" not in body
    assert "private recommendation" not in body


def test_email_headers_and_rule_summary_remove_untrusted_newlines():
    packet = {
        "header": {"change_notice_number": "ECN-1\nBcc: outsider@example.com"},
        "gate": {"decision": "FAIL", "blockers": [{"rule_id": "H01\nInjected", "severity": "ERROR\nInjected"}]},
    }

    subject, body = build_validation_email(packet)

    assert "\n" not in subject
    assert "\nBcc:" not in body
    assert "\nInjected" not in body
    assert "Injected" in body


def test_proofpoint_missing_contract_settings_does_not_make_http_requests():
    calls = []

    result = send_validation_email(PACKET, "tester@fisherpaykel.com", environ={}, http_post=lambda *args, **kwargs: calls.append(args))

    assert result["sent"] is False
    assert result["status"] == "not_configured"
    assert calls == []


def test_proofpoint_rejects_non_internal_recipients_before_http_request():
    calls = []

    result = send_validation_email(PACKET, "outsider@example.com", environ={}, http_post=lambda *args, **kwargs: calls.append(args))

    assert result["sent"] is False
    assert result["status"] == "failed"
    assert calls == []


def test_proofpoint_uses_configured_token_and_send_contract_with_fake_transport():
    environ = {
        "PROOFPOINT_SEND_URL": "https://mail.example.test/send",
        "PROOFPOINT_SENDER_ADDRESS": "ai-ecn-notifications@fisherpaykel.com",
        "PROOFPOINT_CLIENT_ID": "client-id",
        "PROOFPOINT_CLIENT_SECRET": "private-secret",
        "PROOFPOINT_TOKEN_GRANT_TYPE": "client_credentials",
        "PROOFPOINT_TOKEN_SCOPE": "mail.send",
        "PROOFPOINT_TOKEN_RESPONSE_FIELD": "access_token",
        "PROOFPOINT_TOKEN_CLIENT_ID_FIELD": "client_id",
        "PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD": "client_secret",
        "PROOFPOINT_TOKEN_GRANT_TYPE_FIELD": "grant_type",
        "PROOFPOINT_TOKEN_SCOPE_FIELD": "scope",
        "PROOFPOINT_TOKEN_REQUEST_FORMAT": "json",
        "PROOFPOINT_SEND_REQUEST_FORMAT": "json",
        "PROOFPOINT_SEND_FROM_FIELD": "from",
        "PROOFPOINT_SEND_TO_FIELD": "to",
        "PROOFPOINT_SEND_SUBJECT_FIELD": "subject",
        "PROOFPOINT_SEND_BODY_FIELD": "body",
    }
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/token"):
            return Response({"access_token": "private-access-token"})
        return Response({})

    result = send_validation_email(PACKET, "Tester@fisherpaykel.com", environ=environ, http_post=fake_post)

    assert result["sent"] is True
    assert result["status"] == "sent"
    assert len(calls) == 2
    assert calls[0][0].endswith("/v1/token")
    assert calls[1][1]["headers"]["Authorization"] == "Bearer private-access-token"
    assert calls[1][1]["json"]["to"] == "Tester@fisherpaykel.com"
    assert calls[1][1]["json"]["from"] == "ai-ecn-notifications@fisherpaykel.com"
    assert "Reason is missing." not in calls[1][1]["json"]["body"]
    assert environ["PROOFPOINT_CLIENT_SECRET"] not in repr(result)


def test_proofpoint_rejects_insecure_or_credential_bearing_endpoints():
    calls = []
    environ = {
        "PROOFPOINT_SEND_URL": "http://mail.example.test/send",
        "PROOFPOINT_SENDER_ADDRESS": "ai-ecn-notifications@fisherpaykel.com",
        "PROOFPOINT_CLIENT_ID": "client-id",
        "PROOFPOINT_CLIENT_SECRET": "private-secret",
        "PROOFPOINT_TOKEN_GRANT_TYPE": "client_credentials",
        "PROOFPOINT_TOKEN_SCOPE": "mail.send",
        "PROOFPOINT_TOKEN_RESPONSE_FIELD": "access_token",
        "PROOFPOINT_TOKEN_CLIENT_ID_FIELD": "client_id",
        "PROOFPOINT_TOKEN_CLIENT_SECRET_FIELD": "client_secret",
        "PROOFPOINT_TOKEN_GRANT_TYPE_FIELD": "grant_type",
        "PROOFPOINT_SEND_FROM_FIELD": "from",
        "PROOFPOINT_SEND_TO_FIELD": "to",
        "PROOFPOINT_SEND_SUBJECT_FIELD": "subject",
        "PROOFPOINT_SEND_BODY_FIELD": "body",
    }

    result = send_validation_email(PACKET, "tester@fisherpaykel.com", environ=environ, http_post=lambda *args, **kwargs: calls.append(args))

    assert result["status"] == "not_configured"
    assert calls == []


def test_email_body_omits_untrusted_app_urls():
    _, body = build_validation_email(PACKET, "https://user:password@example.test/app?token=secret#fragment")

    assert "Open the ECN Checker" not in body
    assert "password" not in body
    assert "token=secret" not in body
