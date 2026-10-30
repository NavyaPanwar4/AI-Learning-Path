"""UTC clock helpers.

The current schema stores most timestamps as timezone-naive UTC values. Use an
explicit UTC-aware clock and strip tzinfo only at the persistence boundary so
SQLite comparisons stay consistent without relying on deprecated utcnow().
"""
from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Return the current UTC instant as a naive datetime for legacy DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
