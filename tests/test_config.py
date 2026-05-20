from __future__ import annotations

import pytest

import self_sentry
from self_sentry._config import get_config


def test_init_sets_config(fake_slack):
    self_sentry.init(token="xoxb-1", channel="#a", service_name="svc")
    cfg = get_config()
    assert cfg is not None
    assert cfg.token == "xoxb-1"
    assert cfg.channel == "#a"
    assert cfg.service_name == "svc"


def test_init_is_idempotent(fake_slack):
    self_sentry.init(token="xoxb-1", channel="#a", service_name="svc1")
    self_sentry.init(token="xoxb-2", channel="#b", service_name="svc2")
    cfg = get_config()
    assert cfg is not None
    assert cfg.service_name == "svc2"
    assert cfg.token == "xoxb-2"
    assert cfg.channel == "#b"


def test_init_requires_token_and_channel():
    with pytest.raises(TypeError):
        self_sentry.init(service_name="svc")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        self_sentry.init(token="xoxb-1", service_name="svc")  # type: ignore[call-arg]


def test_init_from_env_reads_three_vars(fake_slack, monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "my-svc")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-solo")
    monkeypatch.setenv("SLACK_CHANNEL", "#solo")
    self_sentry.init_from_env()
    cfg = get_config()
    assert cfg is not None
    assert cfg.token == "xoxb-solo"
    assert cfg.channel == "#solo"
    assert cfg.service_name == "my-svc"


def test_init_from_env_noop_without_service_name(fake_slack, monkeypatch):
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-solo")
    monkeypatch.setenv("SLACK_CHANNEL", "#solo")
    self_sentry.init_from_env()
    assert get_config() is None


def test_init_from_env_noop_without_token(fake_slack, monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "svc")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_CHANNEL", "#solo")
    self_sentry.init_from_env()
    assert get_config() is None


def test_init_from_env_noop_without_channel(fake_slack, monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "svc")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-solo")
    monkeypatch.delenv("SLACK_CHANNEL", raising=False)
    self_sentry.init_from_env()
    assert get_config() is None


def test_is_initialized_reflects_state(fake_slack):
    assert self_sentry.is_initialized() is False
    self_sentry.init(token="xoxb-1", channel="#a", service_name="svc")
    assert self_sentry.is_initialized() is True
