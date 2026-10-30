from datetime import datetime, timedelta, timezone

import pytest

from app.services.mastery_decay import (
    MASTERY_BASELINE,
    MASTERY_HALF_LIFE_DAYS,
    decay_mastery,
    elapsed_days,
    review_interval_days,
)


def test_mastery_decays_to_baseline_over_time():
    reviewed = datetime(2026, 1, 1, 12, 0, 0)
    now = reviewed + timedelta(days=MASTERY_HALF_LIFE_DAYS)

    assert decay_mastery(0.8, reviewed, now=now) == pytest.approx(0.5)
    assert decay_mastery(0.8, reviewed, now=reviewed + timedelta(days=90)) < 0.4
    assert decay_mastery(0.8, reviewed, now=reviewed + timedelta(days=180)) == pytest.approx(0.2375, abs=0.002)


def test_mastery_without_review_timestamp_is_not_guessed_to_be_old():
    assert decay_mastery(0.86, None) == pytest.approx(0.86)


def test_decay_does_not_increase_low_mastery_or_exceed_probability_bounds():
    reviewed = datetime(2026, 1, 1)
    now = reviewed + timedelta(days=90)
    assert decay_mastery(0.1, reviewed, now=now) == pytest.approx(0.1)
    assert 0.0 <= decay_mastery(1.5, reviewed, now=now) <= 1.0


def test_review_interval_uses_bkt_probability_and_is_monotonic():
    low = review_interval_days(0.25)
    medium = review_interval_days(0.55)
    high = review_interval_days(0.9)

    assert 1 <= low < medium < high <= 30
    assert review_interval_days(0.9) > review_interval_days(0.8)
    assert review_interval_days(0.0) == 1
    assert review_interval_days(1.0) == 30


def test_elapsed_days_handles_timezone_aware_timestamps():
    reviewed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 1, 4, tzinfo=timezone.utc)
    assert elapsed_days(reviewed, now=now) == pytest.approx(3.0)
