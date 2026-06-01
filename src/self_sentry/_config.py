from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("self_sentry")


@dataclass(frozen=True)
class SelfSentryConfig:
    token: str
    channel: str
    service_name: str
    install_excepthook: bool = True
    install_threading_hook: bool = True
    install_asyncio_hook: bool = True
    lambda_timeout_warning: bool = True
    timeout_warning_buffer_ms: int = 1000
    thread_long_fields: bool = True
    footer: str = "self-sentry"
    sendgrid_api_key: str | None = None
    email_from: str | None = None
    email_to: tuple[str, ...] = ()
    originals: dict[str, Any] = field(default_factory=dict)


def _parse_emails(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Normalize a recipients spec to a tuple of addresses.

    Accepts a comma-separated string ("a@x.com,b@y.com"), an iterable of
    strings, or None. Whitespace is trimmed and empties dropped.
    """
    if value is None:
        return ()
    parts = value.split(",") if isinstance(value, str) else list(value)
    return tuple(p.strip() for p in parts if str(p).strip())


_lock = threading.RLock()
_config: SelfSentryConfig | None = None


def get_config() -> SelfSentryConfig | None:
    return _config


def is_initialized() -> bool:
    return _config is not None


def init(
    token: str,
    *,
    channel: str,
    service_name: str,
    install_excepthook: bool = True,
    install_threading_hook: bool = True,
    install_asyncio_hook: bool = True,
    lambda_timeout_warning: bool = True,
    timeout_warning_buffer_ms: int = 1000,
    thread_long_fields: bool = True,
    footer: str = "self-sentry",
    sendgrid_api_key: str | None = None,
    email_from: str | None = None,
    email_to: str | list[str] | tuple[str, ...] | None = None,
) -> None:
    """Initialize self-sentry. Sentry-style: call once at app startup.

    All reporting goes to one Slack bot, posting to one channel.

    ``thread_long_fields`` is on by default: the alert posts with just
    the short context, and the traceback / event payload move into a
    threaded reply, keeping the channel feed scannable. Pass
    ``thread_long_fields=False`` to get the older single-message shape.

    Email (optional): pass ``sendgrid_api_key``, ``email_from`` and
    ``email_to`` to enable email alerts via SendGrid. ``email_to`` accepts
    a comma-separated string ("a@x.com,b@y.com") or a list. Email is only
    sent when a call opts in with ``send_email=True`` (see ``notify`` /
    ``report_exception`` / ``report_errors``); if those creds are absent,
    a ``send_email=True`` call posts to Slack and logs a warning instead.
    """
    global _config

    cfg = SelfSentryConfig(
        token=token,
        channel=channel,
        service_name=service_name,
        install_excepthook=install_excepthook,
        install_threading_hook=install_threading_hook,
        install_asyncio_hook=install_asyncio_hook,
        lambda_timeout_warning=lambda_timeout_warning,
        timeout_warning_buffer_ms=timeout_warning_buffer_ms,
        thread_long_fields=thread_long_fields,
        footer=footer,
        sendgrid_api_key=sendgrid_api_key,
        email_from=email_from,
        email_to=_parse_emails(email_to),
    )

    with _lock:
        from . import _hooks  # local import to avoid cycles

        if _config is not None:
            _hooks.restore_global_hooks(_config)
        _config = cfg
        _hooks.install_global_hooks(cfg)


def init_from_env() -> None:
    """Initialize from env vars.

    Reads:
        SLACK_BOT_TOKEN   (required)
        SLACK_CHANNEL     (required)
        SERVICE_NAME      (required)
        SENDGRID_API_KEY  (optional — enables email alerts)
        ALERT_EMAIL_FROM  (optional — sender address)
        ALERT_EMAIL_TO    (optional — comma-separated recipients)

    No-op (with warning) if any of the three required vars is unset. The
    email vars are optional; without all three, email alerts stay off.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")
    service_name = os.getenv("SERVICE_NAME")
    if not (token and channel and service_name):
        log.warning(
            "self_sentry.init_from_env(): SLACK_BOT_TOKEN, SLACK_CHANNEL, "
            "and SERVICE_NAME are all required; skipping init",
        )
        return
    init(
        token=token,
        channel=channel,
        service_name=service_name,
        sendgrid_api_key=os.getenv("SENDGRID_API_KEY"),
        email_from=os.getenv("ALERT_EMAIL_FROM"),
        email_to=os.getenv("ALERT_EMAIL_TO"),
    )


def _reset_for_tests() -> None:
    """Internal: drop all state. Tests only."""
    global _config
    with _lock:
        if _config is not None:
            from . import _hooks

            _hooks.restore_global_hooks(_config)
        _config = None
