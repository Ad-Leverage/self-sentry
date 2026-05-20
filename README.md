# self-sentry

Sentry-style Slack error reporting for Python — works in AWS Lambda, FastAPI/Django servers, plain scripts, anywhere.

One `init()` call per project, then:

- `@report_errors()` decorator catches uncaught exceptions and posts to Slack.
- Global hooks (`sys.excepthook`, `threading.excepthook`, asyncio loop handler) catch *anything* you forgot to wrap.
- Lambda timeout watchdog posts a warning ~1s before your function times out (the silent-kill case Lambda gives you nothing for).
- Manual `notify(...)` for ad-hoc info/success/error messages.

## Install

```
pip install git+ssh://git@github.com/Ad-Leverage/self-sentry.git@v0.1.0
```

Pin to a tag, not a branch — that's what makes reproducible Lambda builds work.

## Quickstart

```python
import os
import self_sentry

self_sentry.init(
    token=os.environ["SLACK_BOT_TOKEN"],
    channel="#my-project-alerts",
    service_name="my-service",
)

@self_sentry.report_errors()
def lambda_handler(event, context):
    ...

self_sentry.notify("Booking succeeded", fields={"booking_id": 42}, status=0)
```

### Env-driven init (good for Lambdas that already hydrate secrets)

Set `SLACK_BOT_TOKEN`, `SLACK_CHANNEL`, and `SERVICE_NAME`, then:

```python
self_sentry.init_from_env()
```

No-op (with a warning) if any of the three is missing — safe to call unconditionally at app startup.

## What gets reported

| Source | Fires when |
|---|---|
| `@report_errors()` | The wrapped function raises (re-raised after reporting). |
| `sys.excepthook` | Uncaught exception kills the main thread. |
| `threading.excepthook` | Uncaught exception in a `threading.Thread`. |
| asyncio loop handler | Uncaught exception in a `Task` / `call_soon` callback. (Installed lazily on the first running loop.) |
| Lambda timeout watchdog | `context.get_remaining_time_in_millis()` drops below `timeout_warning_buffer_ms` (default 1000). |

## Configuration

```python
self_sentry.init(
    token="xoxb-...",                # required
    channel="#alerts",               # required
    service_name="my-service",       # shows up as Slack author_name
    install_excepthook=True,
    install_threading_hook=True,
    install_asyncio_hook=True,
    lambda_timeout_warning=True,
    timeout_warning_buffer_ms=1000,
)
```

One bot, one channel. If you need to post to multiple destinations, call `notify(..., channel="#other")` explicitly at the call site.

If `init()` is never called, every reporting function is a silent no-op — safe to leave decorators and `notify()` calls in code that runs locally without Slack creds.

## Status codes (Slack color)

| `status` | Color | Use |
|---|---|---|
| `0` | green | success |
| `1` | orange | error (default for `report_exception`) |
| `2` | grey | debug |
| `3` | purple | info (default for `notify`) |

## Local dev

```
pip install -e ".[dev]"
pytest -q
ruff check src tests
mypy src/self_sentry
```

Manual smoke test against a real Slack workspace:

```
LIVE_SLACK_TOKEN=xoxb-... LIVE_SLACK_CHANNEL='#test' python -m tests.smoke.send_real
```

## Release

Tag-based; no PyPI.

```
git tag v0.1.0 && git push --tags
```

Bump the `@vX.Y.Z` pin in consumer projects to upgrade.

## Caveats

- The asyncio handler is installed *lazily* on the first running loop observed (via `@report_errors` or `report_exception`). Exceptions on a loop that runs before that first call are not captured. Fine for typical FastAPI/Mangum/Lambda layouts.
- The Lambda timeout watchdog uses a `threading.Timer`. It is always cancelled in the decorator's `finally` so it cannot leak across invocations — but if you reach inside and start a watchdog yourself, don't outlive the handler scope.

## License

MIT
