"""self-sentry: Sentry-style Slack error reporting for Python.

Quickstart::

    import self_sentry, os

    self_sentry.init(
        token=os.environ["SLACK_BOT_TOKEN"],
        channel="#alerts",
        service_name="my-service",
    )

    @self_sentry.report_errors()
    def lambda_handler(event, context): ...
"""

from ._client import notify, report_exception
from ._config import init, init_from_env, is_initialized
from ._decorator import report_errors

__version__ = "0.4.0"

__all__ = [
    "__version__",
    "init",
    "init_from_env",
    "is_initialized",
    "report_errors",
    "report_exception",
    "notify",
]
