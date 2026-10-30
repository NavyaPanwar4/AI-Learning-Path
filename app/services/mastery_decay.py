"""Time-aware mastery utilities for BKT and spaced review.

The database stores the latest BKT probability. Because the existing schema has
no per-skill last-reviewed column, ReviewSchedule.created_at is refreshed when a
review is scheduled and existing quiz-question timestamps provide a fallback.
This keeps the change compatible with existing SQLite databases (no migration).
"""

from __future__ import annotations
from app.utils.time import utcnow_naive

from datetime import datetime, timezone
from math import exp, log

from app.db.models import QuizAttempt, QuizQuestionHistory, ReviewSchedule


MASTERY_HALF_LIFE_DAYS = 45.0
MASTERY_BASELINE = 0.20
MAX_REVIEW_INTERVAL_DAYS = 30


def normalize_skill_name(name: str | None) -> str:
    """Normalize skill names for case/whitespace-insensitive matching."""
    return (name or "").strip().casefold()


def _naive_utc(value: datetime) -> datetime:
    """Normalize SQLAlchemy's commonly-naive timestamps and ISO-aware dates."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def elapsed_days(last_reviewed_at: datetime | None, now: datetime | None = None) -> float | None:
    if last_reviewed_at is None:
        return None
    now = _naive_utc(now or utcnow_naive())
    last_reviewed_at = _naive_utc(last_reviewed_at)
    return max(0.0, (now - last_reviewed_at).total_seconds() / 86400.0)


def decay_mastery(
    probability: float | int | None,
    last_reviewed_at: datetime | None,
    now: datetime | None = None,
    half_life_days: float = MASTERY_HALF_LIFE_DAYS,
    baseline: float = MASTERY_BASELINE,
) -> float:
    """Return time-decayed BKT mastery without mutating the persisted value.

    Mastery approaches the learner's baseline at an exponential rate. The
    baseline is capped at the starting probability so decay never increases a
    low score. With a 45-day half-life, a probability of .80 approaches .50
    after 45 days and .35 after 90 days.
    """
    try:
        p = float(probability if probability is not None else baseline)
    except (TypeError, ValueError):
        p = baseline
    p = max(0.0, min(1.0, p))
    days = elapsed_days(last_reviewed_at, now)
    if days is None or days <= 0 or half_life_days <= 0:
        return p
    floor = min(max(0.0, min(1.0, baseline)), p)
    remaining = exp(-log(2.0) * days / half_life_days)
    return max(0.0, min(1.0, floor + (p - floor) * remaining))


def review_interval_days(probability: float | int | None) -> int:
    """Select a continuous, BKT-driven interval in the range 1–30 days.

    The interval scales with the square of the post-quiz BKT probability. This
    is not a score-percent band: a stronger BKT estimate gets a longer interval
    and weaker mastery gets a short-interval retry.
    """
    try:
        p = float(probability if probability is not None else MASTERY_BASELINE)
    except (TypeError, ValueError):
        p = MASTERY_BASELINE
    p = max(0.0, min(1.0, p))
    return max(1, min(MAX_REVIEW_INTERVAL_DAYS, int(round(1 + 29 * p * p))))


def load_last_reviewed_at_by_skill(db, user_id: str, goal_id: str | None = None) -> dict[str, datetime]:
    """Return the latest known review/evidence timestamp for each skill name.

    Review schedule timestamps are refreshed on each quiz review. Quiz question
    history is also consulted so older databases (created before that behavior)
    can still decay from their most recent skill-specific answer timestamp.
    """
    latest: dict[str, datetime] = {}

    def keep_latest(name, timestamp):
        key = normalize_skill_name(name)
        if not key or timestamp is None:
            return
        current = latest.get(key)
        if current is None or _naive_utc(timestamp) > _naive_utc(current):
            latest[key] = timestamp

    schedule_query = db.query(ReviewSchedule.skill_name, ReviewSchedule.created_at).filter(
        ReviewSchedule.user_id == str(user_id)
    )
    if goal_id is not None:
        schedule_query = schedule_query.filter(ReviewSchedule.goal_id == str(goal_id))
    schedule_rows = schedule_query.all()
    for name, timestamp in schedule_rows:
        keep_latest(name, timestamp)

    history_query = (
        db.query(QuizQuestionHistory.skill_name, QuizQuestionHistory.created_at)
        .join(QuizAttempt, QuizQuestionHistory.attempt_id == QuizAttempt.id)
        .filter(
            QuizAttempt.user_id == str(user_id),
            QuizQuestionHistory.skill_name.isnot(None),
        )
    )
    if goal_id is not None:
        history_query = history_query.filter(QuizAttempt.goal_id == str(goal_id))
    history_rows = history_query.all()
    for name, timestamp in history_rows:
        keep_latest(name, timestamp)

    return latest
