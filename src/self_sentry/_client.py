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


def _post(token: str, channel: str, attachment: dict[str, Any]) -> None:
    try:
        client = _web_client(token)
        client.chat_postMessage(channel=channel, attachments=[attachment])
    except Exception as e:  # noqa: BLE001
        # Includes SlackApiError; never let Slack failures break callers.
        log.warning("self_sentry: Slack post failed (channel=%s): %s", channel, e)


def notify(
    title: str,
    message: str = "",
    *,
    status: int = 3,
    fields: dict[str, Any] | None = None,
    channel: str | None = None,
    service_name: str | None = None,
) -> None:
    cfg = get_config()
    if cfg is None:
        return
    if getattr(_in_progress, "active", False):
        return
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
        _post(cfg.token, channel or cfg.channel, attachment)
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
        fields: dict[str, Any] = {"Traceback": _code_block(tb)}
        if context:
            fields.update(context)
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
