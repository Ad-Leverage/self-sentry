# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`self-sentry` is a Sentry-style Slack error-reporting library for Python. One `init()` call wires up a Slack bot + channel; from then on a `@report_errors()` decorator, global `sys`/`threading`/`asyncio` excepthooks, a Lambda timeout watchdog, and a manual `notify()` all post to that one destination. Published to PyPI as `self-sentry`; tag drives the release workflow which builds, publishes to PyPI via Trusted Publishing, and attaches artifacts to a GitHub Release.

## Commands

```bash
pip install -e ".[dev]"                       # dev install
pytest -q                                     # full test suite
pytest tests/test_decorator.py::test_x -q     # single test
ruff check src tests                          # lint (CI gates this)
mypy src/self_sentry                          # type-check (CI gates this)
LIVE_SLACK_TOKEN=xoxb-... LIVE_SLACK_CHANNEL='#test' python -m tests.smoke.send_real  # real Slack smoke
git tag vX.Y.Z && git push --tags             # release: triggers PyPI publish + GH Release
```

CI matrix is Python 3.10 / 3.11 / 3.12; lockstep with `requires-python = ">=3.10"` in `pyproject.toml`.

## Architecture

Single process-wide config object owns all state. Everything else routes through it.

- **`_config.py`** — `init()` builds a frozen `SelfSentryConfig` dataclass, stashes it in module-global `_config` under an `RLock`, and calls `_hooks.install_global_hooks(cfg)`. Re-`init()` calls `restore_global_hooks` on the previous config first so chained installs don't pile up. `is_initialized()` / `get_config()` is the only way other modules read state.
- **`_client.py`** — `notify()` and `report_exception()` are the two posting primitives. Both **silently no-op** if `get_config()` returns `None` — that's the design contract that makes decorators safe to leave in code that runs without Slack creds locally. `_client_cache` keeps one `slack_sdk.WebClient` per token (lazy import; importing the library does *not* drag in `slack_sdk` at module load). `_in_progress` is a `threading.local` re-entry guard so a hook firing during a hook can't recurse infinitely.
- **`_hooks.py`** — `install_global_hooks` chains `sys.excepthook` and `threading.excepthook` (originals saved into `cfg.originals` for later `restore_global_hooks`). The asyncio handler is **lazy** — `try_install_asyncio_handler()` is called from inside `report_errors`'s wrapper on every call and only does work on the first running loop it sees, tracked by `id(loop)` in `_asyncio_installed_loops`. This is deliberate: FastAPI/Mangum decide which loop to use, so hooking at `init()` time would attach to the wrong (or no) loop.
- **`_decorator.py`** — `report_errors()` is the user-facing wrapper. It sniffs `(event, context)` shape via `hasattr(context, "get_remaining_time_in_millis")` and, if it looks like a Lambda invocation, arms a `LambdaTimeoutWatchdog`. Always re-raises; the catch is purely for reporting. `try_install_asyncio_handler()` runs first so async handlers get the loop hook.
- **`_watchdog.py`** — `threading.Timer` set to fire `buffer_ms` before `get_remaining_time_in_millis()` runs out. The decorator's `finally` block **must** cancel it: Lambda freezes the process between invocations, so a leaked timer would fire against a future invocation's context. `_fire` is guarded with `_fired` + a lock so cancel/fire races are safe.
- **`_formatter.py`** — Slack attachment shape + status→color map. Status integers (0=success/green, 1=error/orange, 2=debug/grey, 3=info/purple) are **wire-compatible with our earlier internal bot impl** — don't renumber.

### Invariants worth preserving

- **No-op when uninitialized.** Every public entry point checks `get_config()` and returns silently if `None`. Don't add a code path that raises or logs at error level when init hasn't happened.
- **Never let a Slack failure escape.** `_post()` swallows everything under a `log.warning`. Reporting must not break business code.
- **Lazy `slack_sdk` import.** Keep it inside `_web_client`; don't move to module top-level.
- **Watchdog cancel in `finally`.** Non-negotiable; see the freeze-across-invocations note above.
- **Asyncio hook is lazy and per-loop.** Don't move it into `init()`.

## Tests

`tests/conftest.py` is the entire test harness:

- `FakeWebClient` replaces `slack_sdk.WebClient` and records every `chat_postMessage`. The `fake_slack` fixture installs it via `monkeypatch.setattr(slack_sdk, "WebClient", ...)`.
- `FakeLambdaContext` mimics the bits of `aws_lambda.Context` the watchdog touches.
- `_reset_self_sentry` autouse fixture calls `_reset_for_tests` / `_clear_client_cache_for_tests` / `_reset_asyncio_state_for_tests` on every test — these are internal helpers that exist **only** to undo global state set up by `init()` and the hook installers. If you add new global state, add a reset helper and wire it in here.
- `initialized` fixture = `fake_slack` + `self_sentry.init(token="xoxb-test-1", channel="#alerts", service_name="test-service")`. Use it as the default starting point.

`pytest.ini_options` sets `asyncio_mode = "auto"`, so `async def test_…` runs without an `@pytest.mark.asyncio` marker.

The `tests/smoke/send_real.py` script hits the real Slack API and is intentionally **not** collected by pytest (it's under `tests/smoke/` and runs as `python -m tests.smoke.send_real`).
