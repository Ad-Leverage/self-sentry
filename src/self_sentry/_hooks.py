from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any

log = logging.getLogger("self_sentry")

_asyncio_lock = threading.Lock()
_asyncio_installed_loops: set[int] = set()


def install_global_hooks(cfg: Any) -> None:
    """Install sys/threading hooks. asyncio installs lazily on first use."""
    from ._client import report_exception

    if cfg.install_excepthook:
        prev = sys.excepthook
        cfg.originals["sys.excepthook"] = prev

        def _hook(exc_type, exc, tb):
            try:
                report_exception(exc, context={"source": "sys.excepthook"})
            finally:
                prev(exc_type, exc, tb)

        sys.excepthook = _hook

    if cfg.install_threading_hook:
        prev_t = threading.excepthook
        cfg.originals["threading.excepthook"] = prev_t

        def _t_hook(args):
            try:
                if args.exc_value is not None:
                    report_exception(
                        args.exc_value,
                        context={"source": "threading.excepthook", "thread": args.thread.name if args.thread else "?"},
                    )
            finally:
                prev_t(args)

        threading.excepthook = _t_hook


def restore_global_hooks(cfg: Any) -> None:
    prev = cfg.originals.get("sys.excepthook")
    if prev is not None:
        sys.excepthook = prev
    prev_t = cfg.originals.get("threading.excepthook")
    if prev_t is not None:
        threading.excepthook = prev_t


def try_install_asyncio_handler() -> None:
    """Install asyncio loop exception handler on the currently running loop.

    Safe to call repeatedly. No-op if no loop is running or if already
    installed on this loop. Called lazily from report_errors so we hook
    whatever loop FastAPI/Mangum/etc actually end up using.
    """
    from ._config import get_config

    cfg = get_config()
    if cfg is None or not cfg.install_asyncio_hook:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    loop_id = id(loop)
    with _asyncio_lock:
        if loop_id in _asyncio_installed_loops:
            return
        _asyncio_installed_loops.add(loop_id)

    from ._client import report_exception

    prev_handler = loop.get_exception_handler()

    def _handler(loop_, context):
        exc = context.get("exception")
        if exc is not None:
            try:
                report_exception(
                    exc,
                    context={
                        "source": "asyncio.exception_handler",
                        "message": context.get("message", ""),
                    },
                )
            except Exception as e:  # noqa: BLE001
                log.warning("self_sentry asyncio handler failed: %s", e)
        if prev_handler is not None:
            prev_handler(loop_, context)
        else:
            loop_.default_exception_handler(context)

    loop.set_exception_handler(_handler)


def _reset_asyncio_state_for_tests() -> None:
    with _asyncio_lock:
        _asyncio_installed_loops.clear()
