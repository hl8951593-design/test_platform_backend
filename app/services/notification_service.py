import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings


logger = logging.getLogger(__name__)


def send_plan_run_notification(*, recipients: list[str], plan_name: str, status: str, run_id: int) -> None:
    if not recipients:
        return
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        logger.warning("Plan run %s notification skipped because SMTP is not configured", run_id)
        return

    message = EmailMessage()
    message["Subject"] = f"[Test Plan] {plan_name}: {status}"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = ", ".join(recipients)
    message.set_content(f"Test plan '{plan_name}' finished with status '{status}'. Run ID: {run_id}.")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as client:
        if settings.SMTP_USE_TLS:
            client.starttls()
        if settings.SMTP_USERNAME:
            client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        client.send_message(message)
