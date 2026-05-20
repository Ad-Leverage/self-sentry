from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger("self_sentry")


class LambdaTimeoutWatchdog:
    """Fire a Slack alert ~`buffer_ms` before a Lambda invocation times out.

    Owned by the @report_errors decorator; always cancelled in the
    decorator's `finally` so the timer thread cannot leak across
    invocations (Lambda freezes the process between invocations, so a
    live timer would otherwise fire against a future invocation's context).
    """

    def __init__(
        self,
        context: Any,
        service_name: str,
        buffer_ms: int,
        event_repr: str,
    ) -> None:
        self._context = context
        self._service_name = service_name
        self._buffer_ms = buffer_ms
        self._event_repr = event_repr
        self._timer: threading.Timer | None = None
        self._fired = False
        self._lock = threading.Lock()

    def start(self) -> None:
        try:
            remaining_ms = int(self._context.get_remaining_time_in_millis())
        except Exception as e:  # noqa: BLE001
            log.debug("self_sentry watchdog: get_remaining_time_in_millis failed: %s", e)
            return
        delay_s = max(0.0, (remaining_ms - self._buffer_ms) / 1000.0)
        timer = threading.Timer(delay_s, self._fire)
        timer.daemon = True
        with self._lock:
            self._timer = timer
        timer.start()

    def cancel(self) -> None:
        with self._lock:
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()
            # join with tiny timeout — Timer.cancel() only prevents firing,
            # the thread object still exists; this is cheap insurance.
            timer.join(timeout=0.1)

    def _fire(self) -> None:
        with self._lock:
            if self._fired:
                return
            self._fired = True
        try:
            from ._client import notify
            from ._formatter import _code_block

            try:
                remaining_ms = int(self._context.get_remaining_time_in_millis())
            except Exception:
                remaining_ms = -1
            fields: dict[str, Any] = {
                "remaining_ms": remaining_ms,
                "function_name": getattr(self._context, "function_name", "?"),
                "request_id": getattr(self._context, "aws_request_id", "?"),
                "event": _code_block(self._event_repr),
            }
            notify(
                title="Lambda approaching timeout",
                message=f"Function {fields['function_name']} has < {self._buffer_ms}ms remaining.",
                status=1,
                fields=fields,
                service_name=self._service_name,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("self_sentry watchdog fire failed: %s", e)
