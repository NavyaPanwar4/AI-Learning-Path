"""Robust BKT parameter configuration and population-level calibration.

The estimator fits classical two-state BKT parameters from labelled per-question
response sequences grouped by (user, goal, skill). It uses conservative beta
pseudocounts centered on the configurable defaults and falls back to those
defaults until enough independent response history is available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import func

from app.db.models import QuizAttempt, QuizQuestionHistory
from app.services.mastery_decay import normalize_skill_name
from app.utils.config import settings


@dataclass(frozen=True)
class BKTParameters:
    p_initial: float
    p_learn: float
    p_guess: float
    p_slip: float
    source: str = "configured_fallback"
    response_count: int = 0
    sequence_count: int = 0


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def default_bkt_parameters() -> BKTParameters:
    """Read environment-configurable fallback values and keep them valid."""
    p_initial = _clamp(getattr(settings, "BKT_P_INITIAL", 0.20), 0.01, 0.99)
    p_learn = _clamp(getattr(settings, "BKT_P_LEARN", 0.15), 0.001, 0.50)
    p_guess = _clamp(getattr(settings, "BKT_P_GUESS", 0.20), 0.01, 0.40)
    p_slip = _clamp(getattr(settings, "BKT_P_SLIP", 0.10), 0.01, 0.40)
    if p_guess + p_slip >= 0.95:
        # Avoid a near-uninformative observation model if misconfigured.
        p_guess, p_slip = min(p_guess, 0.35), min(p_slip, 0.35)
    return BKTParameters(p_initial, p_learn, p_guess, p_slip)


def _emission_probability(state: int, correct: bool, p_guess: float, p_slip: float) -> float:
    if state == 0:
        return p_guess if correct else 1.0 - p_guess
    return 1.0 - p_slip if correct else p_slip


def fit_bkt_parameters(
    sequences: Sequence[Sequence[bool]],
    defaults: BKTParameters | None = None,
    *,
    min_responses: int = 100,
    min_sequences: int = 10,
    max_iterations: int = 50,
    tolerance: float = 1e-5,
    prior_strength: float = 10.0,
) -> BKTParameters:
    """Fit shared BKT parameters with a regularized two-state Baum-Welch EM.

    Every sequence represents one learner, one goal, and one skill ordered in
    time. Short or sparse data never produce a pretend personalized fit: the
    configured parameter set is returned unchanged until thresholds are met.
    """
    defaults = defaults or default_bkt_parameters()
    usable = [list(map(bool, seq)) for seq in sequences if len(seq) >= 2]
    response_count = sum(len(seq) for seq in usable)
    sequence_count = len(usable)
    if response_count < min_responses or sequence_count < min_sequences:
        return BKTParameters(
            defaults.p_initial, defaults.p_learn, defaults.p_guess, defaults.p_slip,
            "configured_fallback", response_count, sequence_count,
        )

    p0, pt, pg, ps = defaults.p_initial, defaults.p_learn, defaults.p_guess, defaults.p_slip
    # Beta priors regularize each estimate toward its configured starting value.
    def beta_update(successes: float, trials: float, mean: float, strength: float) -> float:
        alpha = max(0.001, mean * strength)
        beta = max(0.001, (1.0 - mean) * strength)
        return _clamp((successes + alpha) / (trials + alpha + beta), 0.001, 0.999)

    for _ in range(max_iterations):
        init_known = init_total = 0.0
        learned = unmastered_transitions = 0.0
        guessed_correct = unmastered_occupancy = 0.0
        slipped_incorrect = mastered_occupancy = 0.0

        a = ((1.0 - pt, pt), (0.0, 1.0))
        for seq in usable:
            # Scaled forward probabilities (scales avoid underflow on long sequences).
            alpha: list[list[float]] = []
            scales: list[float] = []
            first = [
                (1.0 - p0) * _emission_probability(0, seq[0], pg, ps),
                p0 * _emission_probability(1, seq[0], pg, ps),
            ]
            scale = max(1e-15, sum(first))
            alpha.append([x / scale for x in first])
            scales.append(scale)
            for observation in seq[1:]:
                prior0 = alpha[-1][0] * a[0][0] + alpha[-1][1] * a[1][0]
                prior1 = alpha[-1][0] * a[0][1] + alpha[-1][1] * a[1][1]
                values = [
                    prior0 * _emission_probability(0, observation, pg, ps),
                    prior1 * _emission_probability(1, observation, pg, ps),
                ]
                scale = max(1e-15, sum(values))
                alpha.append([x / scale for x in values])
                scales.append(scale)

            beta = [[1.0, 1.0] for _ in seq]
            for t in range(len(seq) - 2, -1, -1):
                nxt = seq[t + 1]
                beta[t][0] = sum(
                    a[0][j] * _emission_probability(j, nxt, pg, ps) * beta[t + 1][j]
                    for j in (0, 1)
                ) / max(1e-15, scales[t + 1])
                beta[t][1] = sum(
                    a[1][j] * _emission_probability(j, nxt, pg, ps) * beta[t + 1][j]
                    for j in (0, 1)
                ) / max(1e-15, scales[t + 1])

            gammas: list[list[float]] = []
            for t in range(len(seq)):
                vals = [alpha[t][s] * beta[t][s] for s in (0, 1)]
                denom = max(1e-15, sum(vals))
                gammas.append([v / denom for v in vals])

            init_known += gammas[0][1]
            init_total += 1.0
            for t, observation in enumerate(seq):
                unmastered_occupancy += gammas[t][0]
                mastered_occupancy += gammas[t][1]
                if observation:
                    guessed_correct += gammas[t][0]
                else:
                    slipped_incorrect += gammas[t][1]
            for t in range(len(seq) - 1):
                # Only an unmastered learner can transition to mastered.
                observation = seq[t + 1]
                xi01 = (
                    alpha[t][0] * a[0][1]
                    * _emission_probability(1, observation, pg, ps)
                    * beta[t + 1][1]
                ) / max(1e-15, scales[t + 1])
                xi00 = (
                    alpha[t][0] * a[0][0]
                    * _emission_probability(0, observation, pg, ps)
                    * beta[t + 1][0]
                ) / max(1e-15, scales[t + 1])
                denom = max(1e-15, xi01 + xi00)
                learned += xi01 / denom * gammas[t][0]
                unmastered_transitions += gammas[t][0]

        new_p0 = beta_update(init_known, init_total, defaults.p_initial, prior_strength)
        new_pt = beta_update(learned, unmastered_transitions, defaults.p_learn, prior_strength)
        new_pg = beta_update(guessed_correct, unmastered_occupancy, defaults.p_guess, prior_strength)
        # P(slip) is the probability of an incorrect response while mastered.
        new_ps = beta_update(slipped_incorrect, mastered_occupancy, defaults.p_slip, prior_strength)
        new_p0 = _clamp(new_p0, 0.02, 0.98)
        new_pt = _clamp(new_pt, 0.001, 0.50)
        new_pg = _clamp(new_pg, 0.01, 0.40)
        new_ps = _clamp(new_ps, 0.01, 0.40)
        delta = max(abs(new_p0-p0), abs(new_pt-pt), abs(new_pg-pg), abs(new_ps-ps))
        p0, pt, pg, ps = new_p0, new_pt, new_pg, new_ps
        if delta < tolerance:
            break

    return BKTParameters(p0, pt, pg, ps, "empirical_em", response_count, sequence_count)


# Cache the fit until the response corpus changes. SQLite projects typically
# have one process, so this avoids repeatedly fitting an unchanged dataset.
_cached_key: tuple[int, int, tuple[float, float, float, float]] | None = None
_cached_parameters: BKTParameters | None = None


def get_bkt_parameters(db) -> BKTParameters:
    defaults = default_bkt_parameters()
    stats = db.query(func.count(QuizQuestionHistory.id), func.max(QuizQuestionHistory.id)).one()
    key = (int(stats[0] or 0), int(stats[1] or 0), (defaults.p_initial, defaults.p_learn, defaults.p_guess, defaults.p_slip))
    global _cached_key, _cached_parameters
    if key == _cached_key and _cached_parameters is not None:
        return _cached_parameters

    rows = (
        db.query(
            QuizAttempt.user_id,
            QuizAttempt.goal_id,
            QuizQuestionHistory.skill_name,
            QuizQuestionHistory.is_correct,
            QuizAttempt.created_at,
            QuizQuestionHistory.question_index,
            QuizQuestionHistory.id,
        )
        .join(QuizQuestionHistory, QuizQuestionHistory.attempt_id == QuizAttempt.id)
        .filter(QuizQuestionHistory.skill_name.isnot(None))
        .order_by(QuizAttempt.user_id, QuizAttempt.goal_id, QuizAttempt.created_at, QuizQuestionHistory.question_index, QuizQuestionHistory.id)
        .all()
    )
    grouped: dict[tuple[str, str, str], list[bool]] = {}
    for user_id, goal_id, skill_name, is_correct, *_ in rows:
        key_seq = (str(user_id), str(goal_id), normalize_skill_name(skill_name))
        if key_seq[2]:
            grouped.setdefault(key_seq, []).append(bool(is_correct))

    sequences = [values for values in grouped.values() if len(values) >= 2]
    parameters = fit_bkt_parameters(
        sequences,
        defaults,
        min_responses=max(2, int(getattr(settings, "BKT_MIN_CALIBRATION_RESPONSES", 100))),
        min_sequences=max(2, int(getattr(settings, "BKT_MIN_CALIBRATION_SEQUENCES", 10))),
    )
    _cached_key = key
    _cached_parameters = parameters
    return parameters
