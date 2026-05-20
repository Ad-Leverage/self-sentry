from __future__ import annotations

import pytest

import self_sentry
from tests.conftest import FakeLambdaContext


def test_success_path_does_not_post(initialized):
    @self_sentry.report_errors()
    def handler(event, context):
        return {"ok": True}

    result = handler({"x": 1}, FakeLambdaContext(remaining_ms=60_000))
    assert result == {"ok": True}
    assert initialized.instances == [] or initialized.instances[0].calls == []


def test_exception_path_posts_and_reraises(initialized):
    @self_sentry.report_errors("worker-name")
    def handler(event, context):
        raise ValueError("oops")

    with pytest.raises(ValueError, match="oops"):
        handler({"id": 99}, FakeLambdaContext(remaining_ms=60_000))

    assert len(initialized.instances) >= 1
    inst = initialized.instances[0]
    assert len(inst.calls) >= 1
    att = inst.calls[0]["attachments"][0]
    assert att["title"] == "ValueError"
    assert att["author_name"] == "worker-name"  # decorator override
    event_field = next(f for f in att["fields"] if f["title"] == "event")
    assert '"id"' in event_field["value"]


def test_event_truncated_at_1500_chars(initialized):
    huge = {"data": "x" * 5000}

    @self_sentry.report_errors()
    def handler(event, context):
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        handler(huge, FakeLambdaContext())

    att = initialized.instances[0].calls[0]["attachments"][0]
    event_field = next(f for f in att["fields"] if f["title"] == "event")
    # Field is wrapped in a Slack code block, so the truncation marker is now
    # interior, not the suffix.
    assert "...[truncated]" in event_field["value"]
    assert event_field["value"].startswith("```\n") and event_field["value"].endswith("\n```")
    code_block_overhead = len("```\n\n```")
    assert len(event_field["value"]) <= 1500 + len("...[truncated]") + code_block_overhead


def test_non_lambda_function_still_works(initialized):
    @self_sentry.report_errors()
    def plain(x, y):
        if x < 0:
            raise ValueError("negative")
        return x + y

    assert plain(1, 2) == 3
    with pytest.raises(ValueError):
        plain(-1, 2)
    # Should have reported once
    assert len(initialized.instances[0].calls) == 1


def test_decorator_uses_init_service_name_when_omitted(initialized):
    @self_sentry.report_errors()
    def handler(event, context):
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        handler({}, FakeLambdaContext())

    att = initialized.instances[0].calls[0]["attachments"][0]
    assert att["author_name"] == "test-service"


def test_decorator_noop_when_uninitialized(fake_slack):
    @self_sentry.report_errors()
    def handler(event, context):
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        handler({}, FakeLambdaContext())

    assert fake_slack.instances == []
