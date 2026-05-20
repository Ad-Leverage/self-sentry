from __future__ import annotations

from typing import Any

import pytest

import self_sentry
from self_sentry import _client, _config, _hooks


class FakeLambdaContext:
    """Mimics the parts of aws_lambda.Context that the watchdog uses."""

    def __init__(self, remaining_ms: int = 30_000, function_name: str = "fn", request_id: str = "req-1"):
        self._remaining_ms = remaining_ms
        self.function_name = function_name
        self.aws_request_id = request_id

    def get_remaining_time_in_millis(self) -> int:
        return self._remaining_ms


class FakeWebClient:
    """Drop-in replacement for slack_sdk.WebClient.

    Records every chat_postMessage call so tests can assert what was sent.
    """

    instances: list[FakeWebClient] = []

    def __init__(self, token: str):
        self.token = token
        self.calls: list[dict[str, Any]] = []
        FakeWebClient.instances.append(self)

    def chat_postMessage(self, *, channel: str, attachments: list[dict[str, Any]]):
        self.calls.append({"channel": channel, "attachments": attachments})
        return {"ts": "1234.5678"}

    @classmethod
    def reset(cls) -> None:
        cls.instances.clear()


@pytest.fixture(autouse=True)
def _reset_self_sentry():
    """Clean library state between tests."""
    _config._reset_for_tests()
    _client._clear_client_cache_for_tests()
    _hooks._reset_asyncio_state_for_tests()
    FakeWebClient.reset()
    yield
    _config._reset_for_tests()
    _client._clear_client_cache_for_tests()
    _hooks._reset_asyncio_state_for_tests()
    FakeWebClient.reset()


@pytest.fixture
def fake_slack(monkeypatch):
    """Replace slack_sdk.WebClient inside _client with FakeWebClient.

    Returns the FakeWebClient class so tests can introspect calls.
    """
    import slack_sdk

    monkeypatch.setattr(slack_sdk, "WebClient", FakeWebClient)
    return FakeWebClient


@pytest.fixture
def initialized(fake_slack):
    """Library initialized with one token + one channel."""
    self_sentry.init(token="xoxb-test-1", channel="#alerts", service_name="test-service")
    return fake_slack
