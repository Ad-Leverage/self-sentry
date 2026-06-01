from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

from ._client import report_exception
from ._config import get_config
from ._formatter import _code_block, serialize_event
from ._hooks import try_install_asyncio_handler
from ._watchdog import LambdaTimeoutWatchdog

log = logging.getLogger("self_sentry")


def _looks_like_lambda_context(obj: Any) -> bool:
    return hasattr(obj, "get_remaining_time_in_millis")


def report_errors(service_name: str | None = None, *, send_email: bool = False) -> Callable:
    """Decorator: catch uncaught exceptions, post to Slack, re-raise.

    Works on Lambda handlers and plain functions:
      - Lambda handler `(event, context)` — also arms a timeout watchdog
        when `context.get_remaining_time_in_millis` is present.
      - Plain function — just reports + re-raises.

    Usage:
        @report_errors()                  # uses init()'s service_name
        @report_errors("my-worker")       # override
        @report_errors(send_email=True)   # also email the alert (see init())

    Pass ``send_email=True`` to also send an email alert (requires email
    creds configured at ``init()``; otherwise it just logs and posts to Slack).

    Silent no-op if init() was never called or no tokens are configured.
    Always re-raises so business behavior is unaffected.
    """

    def _decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def _wrapper(*args, **kwargs):
            try_install_asyncio_handler()

            watchdog: LambdaTimeoutWatchdog | None = None
            cfg = get_config()
            event_for_report: Any = None

            if len(args) >= 2 and _looks_like_lambda_context(args[1]):
                event_for_report = args[0]
                if cfg is not None and cfg.lambda_timeout_warning:
                    watchdog = LambdaTimeoutWatchdog(
                        context=args[1],
                        service_name=service_name or cfg.service_name,
                        buffer_ms=cfg.timeout_warning_buffer_ms,
                        event_repr=serialize_event(args[0]),
                    )
                    watchdog.start()
            elif args:
                event_for_report = args[0]

            try:
                return fn(*args, **kwargs)
            except BaseException as e:
                try:
                    ctx: dict[str, Any] = {}
                    if event_for_report is not None:
                        ctx["event"] = _code_block(serialize_event(event_for_report))
                    report_exception(
                        e, context=ctx, service_name=service_name, send_email=send_email
                    )
                except Exception as reporter_err:  # noqa: BLE001
                    log.warning("self_sentry report_errors reporter failed: %s", reporter_err)
                raise
            finally:
                if watchdog is not None:
                    watchdog.cancel()

        return _wrapper

    return _decorator
