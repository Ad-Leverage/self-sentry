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
    footer: str = "self-sentry"
    originals: dict[str, Any] = field(default_factory=dict)


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
    footer: str = "self-sentry",
) -> None:
    """Initialize self-sentry. Sentry-style: call once at app startup.

    All reporting goes to one Slack bot, posting to one channel.
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
        footer=footer,
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

    No-op (with warning) if any of them is unset.
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
    init(token=token, channel=channel, service_name=service_name)


def _reset_for_tests() -> None:
    """Internal: drop all state. Tests only."""
    global _config
    with _lock:
        if _config is not None:
            from . import _hooks

            _hooks.restore_global_hooks(_config)
        _config = None
