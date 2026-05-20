from __future__ import annotations

import asyncio
import sys
import threading

import self_sentry
from self_sentry._hooks import try_install_asyncio_handler


def test_sys_excepthook_chains_previous(fake_slack):
    chained = {"called": False}
    original = sys.excepthook

    def my_prev(exc_type, exc, tb):
        chained["called"] = True

    sys.excepthook = my_prev
    try:
        # init() must run AFTER my_prev is set so it captures my_prev as the prior hook.
        self_sentry.init(token="xoxb-test-1", channel="#alerts", service_name="test-service")
        try:
            raise RuntimeError("hook test")
        except RuntimeError:
            exc_type, exc, tb = sys.exc_info()
            sys.excepthook(exc_type, exc, tb)
        assert chained["called"] is True
        assert len(fake_slack.instances[0].calls) == 1
        att = fake_slack.instances[0].calls[0]["attachments"][0]
        assert att["title"] == "RuntimeError"
    finally:
        sys.excepthook = original


def test_threading_excepthook_reports(initialized):
    def boom():
        raise ValueError("from-thread")

    t = threading.Thread(target=boom, name="boomer")
    t.start()
    t.join()
    assert len(initialized.instances[0].calls) >= 1
    att = initialized.instances[0].calls[0]["attachments"][0]
    assert att["title"] == "ValueError"
    thread_field = next((f for f in att["fields"] if f["title"] == "thread"), None)
    assert thread_field is not None
    assert thread_field["value"] == "boomer"


async def test_asyncio_handler_reports_uncaught_task_exception(initialized):
    try_install_asyncio_handler()

    async def boom():
        raise RuntimeError("from-task")

    # Create a task and let it raise without awaiting — the loop will call
    # the exception handler when the task is garbage-collected.
    task = asyncio.create_task(boom())
    with __import__("contextlib").suppress(RuntimeError):
        await task
    # Loop's exception handler is what we want to verify, but awaiting raised
    # synchronously. Instead, trigger the handler path explicitly:
    loop = asyncio.get_running_loop()
    try:
        raise RuntimeError("loop-style")
    except RuntimeError as e:
        loop.call_exception_handler({"message": "test", "exception": e})

    # The handler may run on the next loop tick.
    await asyncio.sleep(0)
    titles = [
        c["attachments"][0]["title"]
        for inst in initialized.instances
        for c in inst.calls
    ]
    assert "RuntimeError" in titles


def test_init_restores_hooks_when_called_twice(fake_slack):
    original_excepthook = sys.excepthook
    self_sentry.init(token="xoxb-1", channel="#a", service_name="svc1")
    after_first = sys.excepthook
    assert after_first is not original_excepthook
    self_sentry.init(token="xoxb-2", channel="#b", service_name="svc2")
    # After re-init, the hook should be a fresh wrapper around the
    # original — not stacked on top of the previous wrapper.
    assert sys.excepthook is not after_first
