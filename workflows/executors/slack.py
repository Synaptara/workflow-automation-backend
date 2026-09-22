import requests

from .base import BaseExecutor
from . import register


@register("slack")
class SlackExecutor(BaseExecutor):
    """config: {"webhook_url": str, "message_template": str}
    message_template supports {field} interpolation from the trigger payload."""

    def execute(self, config: dict, context: dict) -> dict:
        webhook_url = config["webhook_url"]
        template = config.get("message_template", "Workflow triggered: {}")
        try:
            message = template.format(**context)
        except (KeyError, IndexError):
            message = template

        resp = requests.post(webhook_url, json={"text": message}, timeout=5)
        resp.raise_for_status()
        return {"status_code": resp.status_code}
