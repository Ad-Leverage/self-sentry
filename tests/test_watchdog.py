from __future__ import annotations

import time

import pytest

import self_sentry
from self_sentry._watchdog import LambdaTimeoutWatchdog
from tests.conftest import FakeLambdaContext


def test_watchdog_fires_when_not_cancelled(initialized):
    ctx = FakeLambdaContext(remaining_ms=150, function_name="fn", request_id="r1")
    wd = LambdaTimeoutWatchdog(
        context=ctx,
        service_name="svc",
        buffer_ms=50,
        event_repr="{}",
    )
    wd.start()
    # delay should be ~ (150 - 50)/1000 = 100ms — wait long enough.
    time.sleep(0.3)

    assert len(initialized.instances[0].calls) == 1
    att = initialized.instances[0].calls[0]["attachments"][0]
    assert att["title"] == "Lambda approaching timeout"
    fn_field = next(f for f in att["fields"] if f["title"] == "function_name")
    assert fn_field["value"] == "fn"


def test_watchdog_cancelled_before_fire_does_not_post(initialized):
    ctx = FakeLambdaContext(remaining_ms=10_000, function_name="fn", request_id="r1")
    wd = LambdaTimeoutWatchdog(
        context=ctx,
        service_name="svc",
        buffer_ms=1000,
        event_repr="{}",
    )
    wd.start()
    wd.cancel()
    time.sleep(0.2)
    assert initialized.instances == [] or initialized.instances[0].calls == []


def test_decorator_arms_watchdog_for_lambda_handler(initialized):
    @self_sentry.report_errors()
    def slow_handler(event, context):
        time.sleep(0.25)  # outlasts the watchdog
        return "done"

    ctx = FakeLambdaContext(remaining_ms=150, function_name="slow")
    # Watchdog fires ~50ms before the 150ms deadline → ~100ms in.
    # Handler runs 250ms total, so the timer should fire before it returns.
    result = slow_handler({}, ctx)
    assert result == "done"
    time.sleep(0.05)

    titles = [c["attachments"][0]["title"] for c in initialized.instances[0].calls]
    assert "Lambda approaching timeout" in titles


def test_decorator_cancels_watchdog_on_fast_return(initialized):
    @self_sentry.report_errors()
    def fast_handler(event, context):
        return "ok"

    ctx = FakeLambdaContext(remaining_ms=10_000, function_name="fast")
    fast_handler({}, ctx)
    time.sleep(0.2)
    # No timeout post should have been made.
    if initialized.instances:
        titles = [c["attachments"][0]["title"] for c in initialized.instances[0].calls]
        assert "Lambda approaching timeout" not in titles


def test_watchdog_disabled_via_init(fake_slack):
    self_sentry.init(
        token="xoxb-1",
        channel="#a",
        service_name="svc",
        lambda_timeout_warning=False,
    )

    @self_sentry.report_errors()
    def handler(event, context):
        time.sleep(0.2)
        return "ok"

    ctx = FakeLambdaContext(remaining_ms=100)
    handler({}, ctx)
    time.sleep(0.1)
    assert fake_slack.instances == [] or fake_slack.instances[0].calls == []


def test_watchdog_threads_event_when_enabled(fake_slack):
    self_sentry.init(
        token="xoxb-1",
        channel="#a",
        service_name="svc",
        thread_long_fields=True,
    )
    ctx = FakeLambdaContext(remaining_ms=150, function_name="fn", request_id="r1")
    wd = LambdaTimeoutWatchdog(
        context=ctx,
        service_name="svc",
        buffer_ms=50,
        event_repr='{"hello": "world"}',
    )
    wd.start()
    time.sleep(0.3)

    calls = fake_slack.instances[0].calls
    assert len(calls) == 2

    parent, reply = calls[0], calls[1]
    assert parent.get("thread_ts") is None
    assert parent["attachments"][0]["title"] == "Lambda approaching timeout"
    parent_fields = parent["attachments"][0]["fields"]
    # function_name etc. stay on the parent; event moves to the reply.
    assert any(f["title"] == "function_name" for f in parent_fields)
    assert all(f["title"] != "event" for f in parent_fields)

    assert reply["thread_ts"] == "1234.5678"
    event_field = next(f for f in reply["attachments"][0]["fields"] if f["title"] == "event")
    assert "hello" in event_field["value"]


@pytest.mark.parametrize("remaining_ms", [1, 5, 50])
def test_watchdog_handles_near_zero_remaining(initialized, remaining_ms):
    ctx = FakeLambdaContext(remaining_ms=remaining_ms)
    wd = LambdaTimeoutWatchdog(
        context=ctx,
        service_name="svc",
        buffer_ms=1000,  # buffer > remaining → delay clamped to 0
        event_repr="{}",
    )
    wd.start()
    time.sleep(0.1)
    # Should fire immediately
    assert len(initialized.instances[0].calls) == 1
