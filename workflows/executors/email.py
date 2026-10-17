import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email

from . import register
from .base import BaseExecutor

MAX_RECIPIENTS = 5


@register("email")
class EmailExecutor(BaseExecutor):
    def execute(self, app_event: str, step_config: dict, context: dict) -> dict:
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            raise ValueError(
                "EMAIL_HOST_USER / EMAIL_HOST_PASSWORD are not set on the backend."
            )

        raw = str(step_config.get("to") or "")
        recipients = [r.strip() for r in re.split(r"[,;\s]+", raw) if r.strip()]
        if not recipients:
            raise ValueError("Recipient 'to' email address is required.")
        if len(recipients) > MAX_RECIPIENTS:
            raise ValueError(f"At most {MAX_RECIPIENTS} recipients per email.")
        for r in recipients:
            try:
                validate_email(r)
            except ValidationError:
                raise ValueError(f"Invalid email address: {r}")

        subject = " ".join(
            str(step_config.get("subject") or "Orkflo Automation").split()
        )[:200]

        raw_body = str(step_config.get("body") or "")

        # Enforce accountability by injecting the verified sender's email
        owner_email = context.get("_system", {}).get("owner_email", "Unknown User")
        footer = f"\n\n---\nThis is an automated email sent via Orkflo on behalf of verified user: {owner_email}"

        body = raw_body + footer

        try:
            msg = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipients,
                connection=get_connection(timeout=10),
            )
            sent = msg.send(fail_silently=False)
        except Exception as e:
            raise RuntimeError(f"Email send failed: {e}")

        return {"status": 200, "delivered": bool(sent), "recipients": recipients}
