from __future__ import annotations

import pytest

import self_sentry


def test_notify_posts_to_configured_channel(initialized):
    self_sentry.notify("hello", "world", status=0, fields={"k": "v"})
    assert len(initialized.instances) == 1
    inst = initialized.instances[0]
    assert inst.token == "xoxb-test-1"
    assert len(inst.calls) == 1
    call = inst.calls[0]
    assert call["channel"] == "#alerts"
    att = call["attachments"][0]
    assert att["title"] == "hello"
    assert "world" in att["text"]
    assert "*k:* v" in att["text"]  # inline bold-label markdown
    assert att["color"] == "#2eb886"  # status=0 → success green
    assert att["mrkdwn_in"] == ["text"]


def test_notify_explicit_channel_overrides_default(initialized):
    self_sentry.notify("hi", channel="#override")
    assert initialized.instances[0].calls[0]["channel"] == "#override"


def test_init_rejects_missing_channel(fake_slack):
    with pytest.raises(TypeError):
        self_sentry.init(token="xoxb-1", service_name="svc")  # type: ignore[call-arg]


def test_notify_noop_when_uninitialized(fake_slack):
    self_sentry.notify("title")
    assert fake_slack.instances == []


def test_report_exception_includes_traceback(initialized):
    try:
        raise ValueError("boom")
    except ValueError as e:
        self_sentry.report_exception(e, context={"event": "{}"})

    call = initialized.instances[0].calls[0]
    att = call["attachments"][0]
    assert att["title"] == "ValueError"
    # Exception message + fields are now composed into a single markdown body.
    assert att["text"].startswith("boom")
    assert "*Traceback*" in att["text"]
    assert "ValueError: boom" in att["text"]
    assert "*event:* {}" in att["text"]


def test_reentry_guard_prevents_recursion(initialized, monkeypatch):
    """If posting itself triggers another report (via excepthook etc.),
    the inner call must short-circuit."""
    from self_sentry import _client

    call_count = {"n": 0}

    original_post = _client._post

    def reentrant_post(token, channel, attachment, *, thread_ts=None):
        call_count["n"] += 1
        # First call simulates an internal failure path that re-enters notify().
        # The guard should make the inner call a no-op.
        if call_count["n"] == 1:
            self_sentry.notify("re-entered")
        return original_post(token, channel, attachment, thread_ts=thread_ts)

    monkeypatch.setattr(_client, "_post", reentrant_post)
    self_sentry.notify("outer")
    # Outer call happens once; inner re-entry is suppressed.
    assert call_count["n"] == 1


def test_dict_context_renders_as_inline_code_block(initialized):
    """Non-string context values are JSON-pretty-printed into a code block
    on the parent message — they do NOT move to a thread reply."""
    try:
        raise ValueError("boom")
    except ValueError as e:
        self_sentry.report_exception(
            e, context={"data": {"id": 1, "name": "alice"}}
        )

    calls = initialized.instances[0].calls
    # initialized pins thread_long_fields=False, so still one call.
    assert len(calls) == 1
    text = calls[0]["attachments"][0]["text"]
    # Header for the dict field, then a JSON code block underneath.
    assert "*data*" in text
    assert "```\n{" in text
    assert '"name": "alice"' in text


def test_scalar_context_not_code_blocked(initialized):
    """Int/float/bool/None render as plain ``*key:* value`` lines, not code blocks."""
    self_sentry.notify("hi", fields={"count": 42, "ratio": 0.5, "ok": True, "x": None})
    text = initialized.instances[0].calls[0]["attachments"][0]["text"]
    assert "*count:* 42" in text
    assert "*ratio:* 0.5" in text
    assert "*ok:* True" in text
    assert "*x:* None" in text
    assert "```" not in text  # no scalar got wrapped in a code block


def test_thread_long_fields_splits_traceback_into_reply(fake_slack):
    self_sentry.init(
        token="xoxb-1",
        channel="#a",
        service_name="svc",
        thread_long_fields=True,
    )
    try:
        raise ValueError("boom")
    except ValueError as e:
        self_sentry.report_exception(e, context={"user": "alice", "blob": "line-1\nline-2"})

    calls = fake_slack.instances[0].calls
    assert len(calls) == 2

    parent, reply = calls[0], calls[1]

    # Parent: alert with short context only — no traceback, no multi-line blob.
    assert parent.get("thread_ts") is None
    parent_att = parent["attachments"][0]
    assert parent_att["title"] == "ValueError"
    assert "*user:* alice" in parent_att["text"]
    assert "Traceback" not in parent_att["text"]
    assert "line-1" not in parent_att["text"]

    # Reply: threaded against the parent's ts, carries traceback + multi-line blob.
    assert reply["thread_ts"] == "1234.5678"
    reply_text = reply["attachments"][0]["text"]
    assert "*Traceback*" in reply_text
    assert "ValueError: boom" in reply_text
    assert "*blob*" in reply_text
    assert "line-1" in reply_text


def test_slack_api_error_does_not_propagate(fake_slack, monkeypatch):
    self_sentry.init(token="xoxb-1", channel="#a", service_name="svc")

    class ExplodingClient:
        def __init__(self, token):
            self.token = token

        def chat_postMessage(self, **kwargs):
            raise RuntimeError("slack is down")

    import slack_sdk

    monkeypatch.setattr(slack_sdk, "WebClient", ExplodingClient)
    from self_sentry import _client

    _client._clear_client_cache_for_tests()
    # Must not raise
    self_sentry.notify("hello")
