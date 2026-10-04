import resend
from decouple import config as env_config

from . import register
from .base import BaseExecutor


@register("email")
class EmailExecutor(BaseExecutor):
    def execute(self, app_event: str, step_config: dict, context: dict) -> dict:

        # 1. Secure Credential Loading
        api_key = env_config("RESEND_API_KEY", default=None)
        if not api_key:
            raise ValueError(
                "RESEND_API_KEY is missing in backend environment variables."
            )

        resend.api_key = api_key

        # 2. Extract Data from UI Config
        to_email = step_config.get("to")
        subject = step_config.get("subject", "Orkflo Automation")
        body = step_config.get("body", "")

        # 3. Strict Validation
        if not to_email:
            raise ValueError(
                "Recipient 'to' email address is required but was not provided."
            )

        # 4. Payload Construction
        params = {
            # REMINDER: The resend.dev testing domain will ONLY deliver to the email
            # address you signed up to Resend with. Change this to your custom domain
            # (e.g., "noreply@orkflo.com") once verified.
            "from": "Orkflo <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "text": body,
        }

        # 5. Execution & Error Catching
        try:
            resp = resend.Emails.send(params)
            return {"status": 200, "delivered": True, "email_id": resp.get("id")}
        except Exception as e:
            # Catch API outages or bad data and pass the exact error back to your Run logs
            raise RuntimeError(f"Resend API Error: {str(e)}")
