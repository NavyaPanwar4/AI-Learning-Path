"""Periodic retention cleanup for persisted AI tutor conversations."""
from datetime import timedelta
import threading

from app.db.database import SessionLocal
from app.db.models import ChatMessage
from app.utils.config import settings
from app.utils.logger import logger
from app.utils.time import utcnow_naive


def purge_expired_chat_history(now=None) -> int:
    """Permanently remove tutor messages older than the configured retention window."""
    current_time = now or utcnow_naive()
    retention_days = max(1, int(settings.CHAT_HISTORY_RETENTION_DAYS))
    cutoff = current_time - timedelta(days=retention_days)

    db = SessionLocal()
    try:
        deleted = (
            db.query(ChatMessage)
            .filter(ChatMessage.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(deleted or 0)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class ChatHistoryRetentionPoller:
    """Run a global retention sweep at startup and periodically afterwards."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False

        # Purge immediately so expired rows do not wait for the first interval.
        try:
            deleted = purge_expired_chat_history()
            if deleted:
                logger.info("Deleted %s expired AI tutor chat message(s)", deleted)
        except Exception as exc:
            # A cleanup problem must not prevent the API from starting.
            logger.error("Initial AI tutor history cleanup failed: %s", exc)

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="chat-history-retention",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "AI tutor history retention poller started (retention=%s days)",
            settings.CHAT_HISTORY_RETENTION_DAYS,
        )
        return True

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self):
        interval = max(60, int(settings.CHAT_HISTORY_CLEANUP_INTERVAL_SECONDS))
        while not self._stop.wait(interval):
            try:
                deleted = purge_expired_chat_history()
                if deleted:
                    logger.info("Deleted %s expired AI tutor chat message(s)", deleted)
            except Exception as exc:
                logger.error("Scheduled AI tutor history cleanup failed: %s", exc)


chat_history_retention_poller = ChatHistoryRetentionPoller()
