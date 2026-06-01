from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from ._config import SelfSentryConfig

log = logging.getLogger("self_sentry")

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_TIMEOUT_S = 10.0


def email_configured(cfg: SelfSentryConfig) -> bool:
    """True only when a non-blank API key, a sender, and a recipient all exist.

    A present-but-empty (or whitespace-only) API key / sender counts as
    unconfigured — e.g. when the consumer hydrates ``SENDGRID_API_KEY`` from a
    secret that is missing or has no ``API_KEY`` field.
    """
    return bool(
        (cfg.sendgrid_api_key or "").strip()
        and (cfg.email_from or "").strip()
        and cfg.email_to
    )


def _post_sendgrid(api_key: str, payload: dict[str, Any], *, timeout: float = _TIMEOUT_S) -> int:
    """POST one mail/send request to SendGrid and return the HTTP status.

    Isolated network seam so tests can monkeypatch it without real I/O.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — fixed https SendGrid endpoint
        SENDGRID_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.status


def send_error_email(cfg: SelfSentryConfig, subject: str, body: str) -> None:
    """Send an alert email via SendGrid. No-op (with a log) if email isn't
    configured; never raises — a mail failure must not break the caller.
    """
    api_key = (cfg.sendgrid_api_key or "").strip()
    email_from = (cfg.email_from or "").strip()
    if not (api_key and email_from and cfg.email_to):
        log.warning(
            "self_sentry: send_email requested but email is not configured "
            "(need a non-empty sendgrid_api_key, email_from, and at least one "
            "email_to); skipping email",
        )
        return
    payload = {
        "personalizations": [{"to": [{"email": addr} for addr in cfg.email_to]}],
        "from": {"email": email_from},
        "subject": subject or cfg.service_name,
        "content": [{"type": "text/plain", "value": body or subject or ""}],
    }
    try:
        status = _post_sendgrid(api_key, payload)
    except Exception as e:  # noqa: BLE001 — mail must never break business code
        log.warning("self_sentry: SendGrid email failed (to=%s): %s", list(cfg.email_to), e)
        return
    if status >= 300:
        log.warning("self_sentry: SendGrid returned status %s (to=%s)", status, list(cfg.email_to))
    else:
        log.info("self_sentry: alert email sent (status=%s, to=%s)", status, list(cfg.email_to))
