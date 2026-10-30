"""Emails opted-in learners when a study reminder falls due.

Safe with several workers: each reminder is *claimed* with an atomic
``UPDATE ... WHERE emailed_at IS NULL`` before sending, so only one process
sends it. If sending fails the claim is released and the next run retries,
until the reminder is older than REMINDER_EMAIL_MAX_AGE_HOURS.
"""
import threading
from datetime import timedelta

from sqlalchemy import update

from app.db.database import SessionLocal
from app.db.models import StudyReminder, User, Roadmap
from app.services.email_service import email_service
from app.utils.config import settings
from app.utils.logger import logger
from app.utils.time import utcnow_naive

BATCH_SIZE = 100


def send_due_reminders(now=None, send=None) -> int:
    """Send every due, un-emailed reminder for opted-in users. Returns how many were sent."""
    now = now or utcnow_naive()
    send = send or email_service.send_study_reminder
    oldest = now - timedelta(hours=settings.REMINDER_EMAIL_MAX_AGE_HOURS)
    sent = 0
    db = SessionLocal()
    try:
        rows = (
            db.query(StudyReminder, User)
            .join(User, User.user_id == StudyReminder.user_id)
            .filter(
                StudyReminder.completed.is_(False),
                StudyReminder.emailed_at.is_(None),
                StudyReminder.due_at <= now,
                StudyReminder.due_at >= oldest,
                User.email_reminders.is_(True),
                User.email.isnot(None),
            )
            .order_by(StudyReminder.due_at.asc())
            .limit(BATCH_SIZE)
            .all()
        )
        for reminder, user in rows:
            claimed = db.execute(
                update(StudyReminder)
                .where(StudyReminder.id == reminder.id, StudyReminder.emailed_at.is_(None))
                .values(emailed_at=now)
            ).rowcount
            db.commit()
            if claimed != 1:
                continue  # another worker got it
            goal_name = ""
            if reminder.goal_id:
                roadmap = db.query(Roadmap).filter(Roadmap.user_id == reminder.user_id, Roadmap.goal_id == reminder.goal_id).first()
                goal_name = roadmap.goal_name if roadmap else ""
            ok = False
            try:
                ok = bool(send(user.email, reminder.title, reminder.due_at, goal_name))
            except Exception as exc:  # never let one bad send stop the batch
                logger.error("Reminder email failed: %s", exc)
            if ok:
                sent += 1
            else:  # release the claim so a later run can retry
                db.execute(update(StudyReminder).where(StudyReminder.id == reminder.id).values(emailed_at=None))
                db.commit()
        return sent
    finally:
        db.close()


class ReminderEmailPoller:
    """Background thread that runs send_due_reminders on an interval."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def enabled(self) -> bool:
        return bool(settings.REMINDER_EMAILS_ENABLED and settings.SMTP_HOST)

    def start(self) -> bool:
        if not self.enabled() or self._thread:
            return False
        self._thread = threading.Thread(target=self._run, name="reminder-emails", daemon=True)
        self._thread.start()
        logger.info("Reminder email poller started (every %ss)", settings.REMINDER_EMAIL_INTERVAL_SECONDS)
        return True

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(max(30, settings.REMINDER_EMAIL_INTERVAL_SECONDS)):
            try:
                count = send_due_reminders()
                if count:
                    logger.info("Sent %s reminder email(s)", count)
            except Exception as exc:
                logger.error("Reminder email run failed: %s", exc)


reminder_poller = ReminderEmailPoller()
