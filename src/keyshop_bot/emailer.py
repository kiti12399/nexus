import asyncio
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from keyshop_bot.config import Settings


class EmailDeliveryError(RuntimeError):
    pass


async def send_verification_code(settings: Settings, email: str, code: str) -> None:
    try:
        await asyncio.to_thread(_send_verification_code_sync, settings, email, code)
    except Exception as exc:
        raise EmailDeliveryError("Could not send verification email") from exc


def _send_verification_code_sync(settings: Settings, email: str, code: str) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise EmailDeliveryError("SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = "Код подтверждения Nexus AI"
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    message["To"] = email
    message.set_content(
        "\n".join(
            [
                "Ваш код подтверждения Nexus AI:",
                "",
                code,
                "",
                "Код действует 15 минут. Если вы не регистрировались, просто проигнорируйте это письмо.",
            ]
        )
    )
    message.add_alternative(
        f"""\
<!doctype html>
<html lang="ru">
  <body style="font-family:Arial,sans-serif;background:#050508;color:#e8e8f0;padding:24px">
    <div style="max-width:520px;margin:0 auto;background:#13131f;border:1px solid rgba(0,245,196,.25);padding:28px">
      <h1 style="margin:0 0 14px;font-size:22px;color:#00f5c4">Nexus AI</h1>
      <p style="margin:0 0 18px">Ваш код подтверждения:</p>
      <div style="font-size:30px;letter-spacing:8px;font-weight:700;color:#ffffff">{code}</div>
      <p style="margin:22px 0 0;color:#9a9ab8;font-size:14px">Код действует 15 минут. Если вы не регистрировались, просто проигнорируйте это письмо.</p>
    </div>
  </body>
</html>
""",
        subtype="html",
    )

    if settings.smtp_ssl:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=20,
        )
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)

    with smtp:
        if settings.smtp_starttls and not settings.smtp_ssl:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value(),
            )
        smtp.send_message(message)
