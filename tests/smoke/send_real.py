"""Manual smoke test against the real Slack API.

Usage::

    export LIVE_SLACK_TOKEN=xoxb-...
    export LIVE_SLACK_CHANNEL='#some-channel'
    python -m tests.smoke.send_real

Sends three posts: a notify(), a caught exception via the decorator,
and (if you uncomment the last block) a Lambda-timeout watchdog trigger.
Eyeball the channel.
"""

from __future__ import annotations

import contextlib
import os
import time

import self_sentry


def main() -> None:
    token = os.environ.get("LIVE_SLACK_TOKEN")
    channel = os.environ.get("LIVE_SLACK_CHANNEL")
    if not token or not channel:
        raise SystemExit("Set LIVE_SLACK_TOKEN and LIVE_SLACK_CHANNEL")

    self_sentry.init(token=token, channel=channel, service_name="self-sentry-smoke")

    self_sentry.notify(
        "smoke: notify()",
        "If you see this, the basic post path works.",
        status=3,
        fields={"library": "self-sentry", "version": self_sentry.__version__},
    )

    @self_sentry.report_errors("smoke-decorator")
    def will_blow_up(x):
        return 1 / x

    with contextlib.suppress(ZeroDivisionError):
        will_blow_up(0)

    # Watchdog smoke (uncomment to test):
    # class FakeCtx:
    #     function_name = "smoke-fn"
    #     aws_request_id = "smoke-req-1"
    #     def get_remaining_time_in_millis(self):
    #         return 1500
    # @self_sentry.report_errors()
    # def slow(event, context):
    #     time.sleep(2.0)
    # slow({"hello": "world"}, FakeCtx())

    time.sleep(1.0)
    print("Smoke posts sent. Check Slack.")


if __name__ == "__main__":
    main()
