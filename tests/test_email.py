from __future__ import annotations

from typing import Any

import pytest

import self_sentry
from self_sentry import _email
from self_sentry._config import _parse_emails


@pytest.fixture
def capture_sendgrid(monkeypatch):
    """Record SendGrid payloads instead of hitting the network."""
    calls: list[dict[str, Any]] = []

    def _fake_post(api_key: str, payload: dict[str, Any], *, timeout: float = 10.0) -> int:
        calls.append({"api_key": api_key, "payload": payload})
        return 202

    monkeypatch.setattr(_email, "_post_sendgrid", _fake_post)
    return calls


def _init_with_email():
    self_sentry.init(
        token="xoxb-test-1",
        channel="#alerts",
        service_name="test-service",
        thread_long_fields=False,
        sendgrid_api_key="SG.test-key",
        email_from="alerts@co.com",
        email_to="a@co.com, b@co.com",
    )


# --- recipient parsing -------------------------------------------------------

def test_parse_emails_comma_string():
    assert _parse_emails("a@x.com, b@y.com ,, c@z.com") == ("a@x.com", "b@y.com", "c@z.com")


def test_parse_emails_list_and_none():
    assert _parse_emails(["a@x.com", " b@y.com "]) == ("a@x.com", "b@y.com")
    assert _parse_emails(None) == ()
    assert _parse_emails("") == ()


# --- notify(send_email=...) --------------------------------------------------

def test_notify_send_email_true_posts_slack_and_email(fake_slack, capture_sendgrid):
    _init_with_email()
    self_sentry.notify("Cookie expired", "session is dead", status=1,
                        fields={"builder_id": 106609}, send_email=True)

    # Slack still posts.
    assert len(fake_slack.instances[0].calls) == 1
    # Exactly one email, addressed to both recipients, with our content.
    assert len(capture_sendgrid) == 1
    payload = capture_sendgrid[0]["payload"]
    assert capture_sendgrid[0]["api_key"] == "SG.test-key"
    assert payload["from"] == {"email": "alerts@co.com"}
    assert payload["personalizations"][0]["to"] == [{"email": "a@co.com"}, {"email": "b@co.com"}]
    assert payload["subject"] == "[test-service] Cookie expired"
    body = payload["content"][0]["value"]
    assert "session is dead" in body
    assert "builder_id: 106609" in body


def test_notify_default_does_not_email(fake_slack, capture_sendgrid):
    _init_with_email()
    self_sentry.notify("hello", "world", status=1)  # send_email defaults False
    assert len(fake_slack.instances[0].calls) == 1
    assert capture_sendgrid == []


def test_notify_send_email_without_config_posts_slack_only(fake_slack, capture_sendgrid, caplog):
    # No email creds configured.
    self_sentry.init(token="xoxb-test-1", channel="#alerts", service_name="svc",
                     thread_long_fields=False)
    self_sentry.notify("oops", status=1, send_email=True)
    assert len(fake_slack.instances[0].calls) == 1  # Slack still went out
    assert capture_sendgrid == []                    # but no email
    assert "not configured" in caplog.text.lower()


# --- report_exception(send_email=...) ---------------------------------------

def test_report_exception_send_email_includes_traceback(fake_slack, capture_sendgrid):
    _init_with_email()
    try:
        raise ValueError("boom")
    except ValueError as e:
        self_sentry.report_exception(e, context={"event": "{}"}, send_email=True)

    # Exactly one email despite Slack possibly posting multiple messages.
    assert len(capture_sendgrid) == 1
    payload = capture_sendgrid[0]["payload"]
    assert payload["subject"] == "[test-service] ValueError"
    body = payload["content"][0]["value"]
    assert body.startswith("boom")
    assert "Traceback" in body
    assert "ValueError: boom" in body


def test_report_exception_default_does_not_email(fake_slack, capture_sendgrid):
    _init_with_email()
    try:
        raise ValueError("boom")
    except ValueError as e:
        self_sentry.report_exception(e)
    assert capture_sendgrid == []


# --- send_error_email guard --------------------------------------------------

def test_send_error_email_noop_when_unconfigured(monkeypatch):
    """email_configured False → never calls the network seam."""
    from self_sentry._config import SelfSentryConfig

    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return 202

    monkeypatch.setattr(_email, "_post_sendgrid", _boom)
    cfg = SelfSentryConfig(token="t", channel="#c", service_name="s")  # no email fields
    _email.send_error_email(cfg, "subj", "body")
    assert called["n"] == 0


@pytest.mark.parametrize("api_key", ["", "   ", None])
def test_blank_api_key_disables_email(fake_slack, capture_sendgrid, api_key):
    """A present-but-empty/whitespace API key counts as unconfigured."""
    self_sentry.init(
        token="xoxb-test-1",
        channel="#alerts",
        service_name="svc",
        thread_long_fields=False,
        sendgrid_api_key=api_key,
        email_from="alerts@co.com",
        email_to="a@co.com",
    )
    self_sentry.notify("oops", status=1, send_email=True)
    assert len(fake_slack.instances[0].calls) == 1  # Slack still posts
    assert capture_sendgrid == []                    # but no email
