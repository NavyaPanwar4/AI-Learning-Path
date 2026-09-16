import smtplib
from email.mime.text import MIMEText

from app.utils.config import settings
from app.utils.logger import logger


class EmailService:
    def send_password_reset(self, to_email: str, reset_link: str):
        if not settings.SMTP_HOST:
            logger.info(f"[DEV — no SMTP configured] Password reset link for {to_email}: {reset_link}")
            return

        msg = MIMEText(
            "We received a request to reset your Learning Path password.\n\n"
            f"Reset it here (expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes):\n{reset_link}\n\n"
            "If you didn't request this, you can safely ignore this email."
        )
        msg["Subject"] = "Reset your Learning Path password"
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.EMAIL_FROM, [to_email], msg.as_string())
        except Exception as e:
            logger.error(f"Failed to send password reset email to {to_email}: {e}")
            logger.info(f"[FALLBACK] Password reset link for {to_email}: {reset_link}")


email_service = EmailService()