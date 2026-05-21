from __future__ import annotations

import json
import traceback
from typing import Any

# Status integer -> Slack color mapping. Kept wire-compatible with earlier
# internal bot implementations; do not renumber.
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


def _format_field(key: str, val: Any) -> str:
    """Render one field as a markdown chunk for the attachment body.

    Short scalars and single-line strings render inline as ``*key:* value``.
    Pre-stringified multi-line content (e.g. a wrapped traceback) and
    structured values (dict/list/obj, pretty-printed as JSON) render as a
    ``*key*`` header on one line followed by their content underneath.
    """
    if isinstance(val, str):
        if "\n" in val:
            return f"*{key}*\n{val}"
        return f"*{key}:* {val}"
    if val is None or isinstance(val, (int, float, bool)):
        return f"*{key}:* {val}"
    try:
        pretty = json.dumps(val, indent=2, default=str)
    except (TypeError, ValueError):
        pretty = repr(val)
    return f"*{key}*\n{_code_block(pretty)}"


def build_attachment(
    service_name: str,
    status: int,
    title: str,
    message: str,
    fields: dict[str, Any] | None,
    footer: str = "self-sentry",
) -> dict[str, Any]:
    body_parts: list[str] = []
    if message:
        body_parts.append(message)
    if fields:
        body_parts.append("\n".join(_format_field(k, v) for k, v in fields.items()))
    body = "\n\n".join(body_parts)
    return {
        "color": get_color(status),
        "author_name": service_name,
        "title": title,
        "text": body,
        "footer": footer,
        "mrkdwn_in": ["text"],
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
