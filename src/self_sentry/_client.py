from __future__ import annotations

import logging
import threading
from typing import Any

from ._config import get_config
from ._formatter import _code_block, build_attachment, truncate_traceback

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
        return _post(cfg.token, channel or cfg.channel, attachment, thread_ts=thread_ts)
    finally:
        _in_progress.active = False


def report_exception(
    exc: BaseException,
    *,
    context: dict[str, Any] | None = None,
    service_name: str | None = None,
) -> None:
    cfg = get_config()
    if cfg is None:
        return
    try:
        tb = truncate_traceback(exc)
        ctx = dict(context) if context else {}
        if cfg.thread_long_fields:
            # Multi-line context entries (event JSON etc.) follow the
            # traceback into the thread reply so the channel feed stays
            # to one short row per alert.
            long_fields = {k: v for k, v in ctx.items() if "\n" in str(v)}
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
    except Exception as reporter_err:  # noqa: BLE001
        log.warning("self_sentry.report_exception failed: %s", reporter_err)


def _clear_client_cache_for_tests() -> None:
    with _client_lock:
        _client_cache.clear()
