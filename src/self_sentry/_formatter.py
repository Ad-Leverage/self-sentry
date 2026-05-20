from __future__ import annotations

import json
import traceback
from typing import Any

# Status semantics borrowed from the original earlier-internal-bot impl so
# Slack color coding stays consistent across projects that migrate over.
_COLOR_BY_STATUS = {
    0: "#2eb886",  # success / book
    1: "#f4a913",  # error
    2: "#808280",  # function / debug
    3: "#7664fb",  # info
}


def get_color(status: int) -> str | None:
    return _COLOR_BY_STATUS.get(status)


def _code_block(s: str) -> str:
    return f"```\n{s}\n```"


def _format_field_value(val: Any) -> str:
    """Stringify a Slack field value, wrapping structured types in a code block.

    Strings pass through unchanged so callers that pre-wrapped (traceback,
    serialized event) keep their formatting. Scalars (int/float/bool/None)
    render as plain strings so things like ``remaining_ms=-1`` don't get a
    code-block wrapper. Anything else — dicts, lists, dataclasses, custom
    objects — is JSON-pretty-printed and wrapped in a triple-backtick block.
    """
    if isinstance(val, str):
        return val
    if val is None or isinstance(val, (int, float, bool)):
        return str(val)
    try:
        pretty = json.dumps(val, indent=2, default=str)
    except (TypeError, ValueError):
        pretty = repr(val)
    return _code_block(pretty)


def build_attachment(
    service_name: str,
    status: int,
    title: str,
    message: str,
    fields: dict[str, Any] | None,
    footer: str = "self-sentry",
) -> dict[str, Any]:
    attachment_fields = []
    if fields:
        for key, val in fields.items():
            value_str = _format_field_value(val)
            attachment_fields.append(
                {"title": key, "value": value_str, "short": "\n" not in value_str}
            )
    return {
        "color": get_color(status),
        "author_name": service_name,
        "title": title,
        "text": message,
        "fields": attachment_fields,
        "footer": footer,
        "mrkdwn_in": ["fields"],
    }


def truncate_traceback(exc: BaseException, max_chars: int = 3000) -> str:
    tb = traceback.format_exc()
    if not tb or tb.strip() == "NoneType: None":
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(tb) > max_chars:
        tb = tb[-max_chars:]
    return tb


def serialize_event(event: Any, max_chars: int = 1500) -> str:
    try:
        body = json.dumps(event, default=str)
    except Exception:
        body = repr(event)
    if len(body) > max_chars:
        body = body[:max_chars] + "...[truncated]"
    return body
