from urllib.parse import urlparse

import requests

from . import register
from .base import BaseExecutor


@register("slack")
class SlackExecutor(BaseExecutor):
    """Config: {"webhook_url": str, "text": str}"""

    def execute(self, app_event: str, config: dict, context: dict) -> dict:
        url = str(config.get("webhook_url") or "").strip()
        p = urlparse(url)
        if p.scheme != "https" or p.hostname not in (
            "hooks.slack.com",
            "hooks.slack-gov.com",
        ):
            raise ValueError(
                "Slack webhook URL must start with https://hooks.slack.com/"
            )

        text = str(config.get("text") or "Workflow triggered!")
        resp = requests.post(
            url, json={"text": text}, timeout=10, allow_redirects=False
        )
        resp.raise_for_status()
        return {"status_code": resp.status_code}
