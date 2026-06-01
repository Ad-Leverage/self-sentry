"""self-sentry: Sentry-style Slack (+ optional email) error reporting for Python.

Quickstart::

    import self_sentry, os

    self_sentry.init(
        token=os.environ["SLACK_BOT_TOKEN"],
        channel="#alerts",
        service_name="my-service",
        # optional email alerts via SendGrid:
        sendgrid_api_key=os.environ.get("SENDGRID_API_KEY"),
        email_from="alerts@my-co.com",
        email_to="a@my-co.com,b@my-co.com",
    )

    @self_sentry.report_errors()
    def lambda_handler(event, context): ...

    # opt in to email per call:
    self_sentry.notify("Cookie expired", status=1, send_email=True)
"""

from ._client import notify, report_exception
from ._config import init, init_from_env, is_initialized
from ._decorator import report_errors

__version__ = "0.5.0"

__all__ = [
    "__version__",
    "init",
    "init_from_env",
    "is_initialized",
    "report_errors",
    "report_exception",
    "notify",
]
