from __future__ import annotations

import logging
import threading
from typing import Any

from ._config import get_config
from ._email import send_error_email
from ._formatter import _code_block, build_attachment, build_email_body, truncate_traceback

log = logging.getLogger("self_sentry")

_in_progress = threading.local()
_client_lock = threading.Lock()
_client_cache: dict[str, Any] = {}


def _web_client(token: str) -> Any:
    # Lazy import so importing self_sentry doesn't force slack_sdk
    # initialization at module import time.
    with _client_lock:
        client = _client_cache.get(token)
        if client is not None:
            return client
        from slack_sdk import WebClient

        client = WebClient(token=token)
        _client_cache[token] = client
        return client


def _post(
    token: str,
    channel: str,
    attachment: dict[str, Any],
    *,
    thread_ts: str | None = None,
) -> str | None:
    try:
        client = _web_client(token)
        kwargs: dict[str, Any] = {"channel": channel, "attachments": [attachment]}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        resp = client.chat_postMessage(**kwargs)
        return resp.get("ts") if resp is not None else None
    except Exception as e:  # noqa: BLE001
        # Includes SlackApiError; never let Slack failures break callers.
        log.warning("self_sentry: Slack post failed (channel=%s): %s", channel, e)
        return None


def notify(
    title: str,
    message: str = "",
    *,
    status: int = 3,
    fields: dict[str, Any] | None = None,
    channel: str | None = None,
    service_name: str | None = None,
    thread_ts: str | None = None,
    send_email: bool = False,
) -> str | None:
    cfg = get_config()
    if cfg is None:
        return None
    if getattr(_in_progress, "active", False):
        return None
    _in_progress.active = True
    try:
        attachment = build_attachment(
            service_name=service_name or cfg.service_name,
            status=status,
            title=title,
            message=message,
            fields=fields,
            footer=cfg.footer,
        )
        ts = _post(cfg.token, channel or cfg.channel, attachment, thread_ts=thread_ts)
        if send_email:
            subject = f"[{service_name or cfg.service_name}] {title}".strip()
            send_error_email(cfg, subject, build_email_body(message, fields))
        return ts
    finally:
        _in_progress.active = False


def report_exception(
    exc: BaseException,
    *,
    context: dict[str, Any] | None = None,
    service_name: str | None = None,
    send_email: bool = False,
) -> None:
    cfg = get_config()
    if cfg is None:
        return
    try:
        tb = truncate_traceback(exc)
        ctx = dict(context) if context else {}
        if cfg.thread_long_fields:
            # Only pre-stringified multi-line content (traceback, the
            # decorator's serialize_event output) goes to the thread.
            # Structured user values (dict/list/obj) are auto-code-blocked
            # by build_attachment but stay inline on the parent.
            long_fields = {k: v for k, v in ctx.items() if isinstance(v, str) and "\n" in v}
            short_fields = {k: v for k, v in ctx.items() if k not in long_fields}
            ts = notify(
                title=type(exc).__name__,
                message=str(exc) or repr(exc),
                status=1,
                fields=short_fields,
                service_name=service_name,
            )
            if ts:
                thread_fields: dict[str, Any] = {"Traceback": _code_block(tb), **long_fields}
                notify(
                    title="",
                    status=1,
                    fields=thread_fields,
                    service_name=service_name,
                    thread_ts=ts,
                )
        else:
            fields: dict[str, Any] = {"Traceback": _code_block(tb), **ctx}
            notify(
                title=type(exc).__name__,
                message=str(exc) or repr(exc),
                status=1,
                fields=fields,
                channel=None,
                service_name=service_name,
            )
        # One email carrying the full picture (raw traceback + context),
        # independent of how Slack split it across the parent/thread.
        if send_email:
            subject = f"[{service_name or cfg.service_name}] {type(exc).__name__}"
            email_fields: dict[str, Any] = {"Traceback": tb, **ctx}
            send_error_email(cfg, subject, build_email_body(str(exc) or repr(exc), email_fields))
    except Exception as reporter_err:  # noqa: BLE001
        log.warning("self_sentry.report_exception failed: %s", reporter_err)


def _clear_client_cache_for_tests() -> None:
    with _client_lock:
        _client_cache.clear()
