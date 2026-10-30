"""Community signals (ratings and reports) that adjust resource ranking.

Learners rate resources 1-5 (UserFeedback, content_type "resource", content_id
= the resource URL) and can report broken or off-topic links (ResourceReport).
Both feed back into which candidates are shown:

* Ratings are smoothed toward a neutral 3.0 so one enthusiastic or angry vote
  cannot move a resource. Three 5-star ratings are worth half of MAX_BONUS,
  and the bonus approaches MAX_BONUS as ratings accumulate.
* A resource is hidden once it has several low ratings or several open reports
  from different learners.

Everything here is best-effort: if the database cannot be read, resources are
ranked exactly as before.
"""
from typing import Dict, Iterable, List, Tuple

from app.db.database import SessionLocal
from app.db.models import ResourceReport, UserFeedback
from app.utils.logger import logger

PRIOR_MEAN = 3.0
PRIOR_WEIGHT = 3          # how many "neutral votes" the smoothing adds
MAX_BONUS = 20.0          # rank points at the extreme
MIN_RATINGS_TO_HIDE = 3
HIDE_AVERAGE_AT_OR_BELOW = 2.0
HIDE_AT_OPEN_REPORTS = 2  # distinct learners


def normalize_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").casefold()


def load_signals(urls: Iterable[str]) -> Dict[str, Dict]:
    """Return {normalized url: {"count", "avg", "reports"}} for urls that have any signal."""
    wanted = {normalize_url(u): u for u in urls if u}
    if not wanted:
        return {}
    originals = set(wanted.values())
    try:
        db = SessionLocal()
    except Exception as exc:
        logger.warning("Could not open the database for resource signals: %s", exc)
        return {}
    try:
        signals: Dict[str, Dict] = {}
        ratings = (
            db.query(UserFeedback.content_id, UserFeedback.rating)
            .filter(UserFeedback.content_type == "resource", UserFeedback.content_id.in_(originals))
            .all()
        )
        for content_id, rating in ratings:
            if rating is None:
                continue
            entry = signals.setdefault(normalize_url(content_id), {"count": 0, "total": 0, "reporters": set()})
            entry["count"] += 1
            entry["total"] += int(rating)
        reports = (
            db.query(ResourceReport.resource_url, ResourceReport.user_id)
            .filter(ResourceReport.resource_url.in_(originals), ResourceReport.status == "open")
            .all()
        )
        for resource_url, reporter in reports:
            entry = signals.setdefault(normalize_url(resource_url), {"count": 0, "total": 0, "reporters": set()})
            entry["reporters"].add(reporter)
        return {
            key: {
                "count": e["count"],
                "avg": (e["total"] / e["count"]) if e["count"] else None,
                "reports": len(e["reporters"]),
            }
            for key, e in signals.items()
        }
    except Exception as exc:  # never let ranking depend on the feedback tables
        logger.warning("Could not load community resource signals: %s", exc)
        return {}
    finally:
        db.close()


def adjustment(signal: Dict) -> Tuple[bool, float]:
    """Return (hide, rank_bonus) for one resource's signal."""
    if not signal:
        return False, 0.0
    count, avg, reports = signal.get("count", 0), signal.get("avg"), signal.get("reports", 0)
    if reports >= HIDE_AT_OPEN_REPORTS:
        return True, 0.0
    if count >= MIN_RATINGS_TO_HIDE and avg is not None and avg <= HIDE_AVERAGE_AT_OR_BELOW:
        return True, 0.0
    if not count or avg is None:
        return False, 0.0
    smoothed = (avg * count + PRIOR_MEAN * PRIOR_WEIGHT) / (count + PRIOR_WEIGHT)
    bonus = (smoothed - PRIOR_MEAN) / 2.0 * MAX_BONUS     # smoothed is within [1, 5]
    return False, max(-MAX_BONUS, min(MAX_BONUS, bonus))


def apply_signals(candidates: List[Dict], signals: Dict[str, Dict]) -> List[Dict]:
    """Drop hidden resources and record each remaining one's bonus.

    The bonus is assigned, not accumulated, so applying signals twice (as
    happens when a cached shortlist is re-checked) gives the same result.
    """
    result = []
    for resource in candidates:
        hide, bonus = adjustment(signals.get(normalize_url(resource.get("url"))))
        if hide:
            continue
        resource["community_bonus"] = bonus
        result.append(resource)
    return result
