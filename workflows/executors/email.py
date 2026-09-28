import resend
from decouple import config as env_config

from . import register
from .base import BaseExecutor


@register("email")
class EmailExecutor(BaseExecutor):
    """
    Requires config: {"to": str, "subject": str, "body": str}
    """

    def execute(self, config: dict, context: dict) -> dict:
        # Load API key directly from your .env file
        resend.api_key = env_config("RESEND_API_KEY")

        to_email = config.get("to")
        subject = config.get("subject", "Flowly Automation")
        body = config.get("body", "")

        params = {
            # Use Resend's free testing domain email
            "from": "Flowly <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "text": body,
        }

        resp = resend.Emails.send(params)
        return {"email_id": resp.get("id")}
