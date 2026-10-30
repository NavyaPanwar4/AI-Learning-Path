import smtplib
import uuid
from email.mime.text import MIMEText

from app.utils.config import settings
from app.utils.logger import logger


class EmailService:
    def send(self, to_email: str, subject: str, body: str) -> bool:
        """Send a plain-text email through the configured SMTP server. Returns True on success."""
        if not settings.SMTP_HOST:
            return False
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to_email
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.EMAIL_FROM, [to_email], msg.as_string())
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def send_password_reset(self, to_email: str, reset_link: str):
        if not settings.SMTP_HOST:
            logger.warning("Password reset email unavailable: SMTP is not configured (request %s)", uuid.uuid4().hex)
            return
        self.send(
            to_email,
            "Reset your Learning Path password",
            "We received a request to reset your Learning Path password.\n\n"
            f"Reset it here (expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes):\n{reset_link}\n\n"
            "If you didn't request this, you can safely ignore this email.",
        )

    def send_study_reminder(self, to_email: str, title: str, due_at, goal_name: str = "") -> bool:
        link = f"{settings.FRONTEND_URL.rstrip('/')}/study-planner"
        about = f" for your {goal_name} path" if goal_name else ""
        return self.send(
            to_email,
            f"Study reminder: {title}",
            f"This is your reminder{about}:\n\n  {title}\n  Due {due_at:%Y-%m-%d %H:%M} UTC\n\n"
            f"Open your study planner: {link}\n\n"
            "You are receiving this because you turned on email reminders. "
            "You can turn them off any time on the Study Planner page.",
        )


email_service = EmailService()
