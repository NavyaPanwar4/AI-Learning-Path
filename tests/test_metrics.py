"""Hand-computed checks for experiments/metrics.py.

Graph: a->b, a->c, b->d, c->d, d->e ; hours a10 b20 c5 d30 e15.
Target is always 'e'; weak < 0.50, strong >= 0.85.
"""
import pytest

from app.services.path_planner import SkillGraph, SkillNode
from experiments import metrics as M


def graph():
    nodes = [SkillNode(s, s, 1, h) for s, h in [("a", 10), ("b", 20), ("c", 5), ("d", 30), ("e", 15)]]
    return SkillGraph(nodes, [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "e")])


def path(*ids):
    return [{"skill_id": s, "action": "learn", "phase": 0} for s in ids]


def score(p, mastery):
    return M.score_path(p, M.ScoreContext(graph(), mastery, ["e"]))


ZERO = {s: 0.0 for s in "abcde"}


def test_perfect_beginner_path():
    r = score(path("a", "b", "c", "d", "e"), ZERO)
    assert r["pvr"] == 0.0 and r["pvr_pairs"] == 5
    assert r["oc"] == 1.0 and r["wsc"] == 1.0 and r["rr"] == 0.0
    assert r["ma"] == pytest.approx(1.0)
    assert r["frontier_at_k"] == pytest.approx(1 / 3)       # fringe={a}; head a,b,c
    assert r["skip_rate"] is None and r["goal_coverage"] == 1.0


def test_fully_reversed_path():
    r = score(path("e", "d", "b", "c", "a"), ZERO)
    assert r["pvr"] == 1.0 and r["pvr_order"] == 1.0 and r["pvr_omit"] == 0.0
    assert r["oc"] == 0.0 and r["pvr_any_violation"] == 1.0


def test_omitted_prerequisites():
    r = score(path("d", "e"), ZERO)
    assert r["pvr_pairs"] == 3 and r["pvr"] == pytest.approx(2 / 3) and r["pvr_omit"] == pytest.approx(2 / 3)
    assert r["pvr_order"] == 0.0
    assert r["goal_coverage"] == pytest.approx(2 / 5) and r["wsc"] == pytest.approx(2 / 5)


def test_planner_like_path_for_mixed_learner():
    m = {"a": 0.9, "b": 0.6, "c": 0.9, "d": 0.1, "e": 0.0}
    r = score(path("b", "d", "e"), m)
    assert r["pvr_pairs"] == 2 and r["pvr"] == 0.0          # satisfied prerequisites are not counted
    assert r["wsc"] == 1.0 and r["rr"] == 0.0 and r["skip_rate"] == 1.0
    assert r["frontier_at_k"] == pytest.approx(1 / 3)       # fringe={b}
    assert r["ma"] == pytest.approx(89 / 111)               # TV similarity, hand computed
    assert r["goal_coverage"] == 1.0 and r["target_coverage"] == 1.0 and r["off_goal_rate"] == 0.0


def test_redundancy_counts_mastered_items():
    m = {"a": 0.95, "b": 0, "c": 0, "d": 0, "e": 0}
    r = score(path("a", "b", "c", "d", "e"), m)
    assert r["rr"] == pytest.approx(1 / 5) and r["rr_hours"] == pytest.approx(10 / 80)
    assert r["skip_rate"] == 0.0


def test_invalid_and_duplicate_items():
    r = score(path("a", "zzz", "a", "b"), ZERO)
    assert r["invalid_rate"] == pytest.approx(0.25) and r["duplicate_rate"] == pytest.approx(0.25)
    assert r["n_items"] == 2


def test_empty_path_conventions():
    r = score([], ZERO)
    assert r["rr"] == 0.0 and r["pvr"] is None and r["ma"] is None
    assert r["wsc"] == 0.0 and r["goal_coverage"] == 0.0


def test_all_mastered_learner_with_empty_path_is_ideal():
    r = score([], {s: 0.95 for s in "abcde"})
    assert r["wsc"] is None and r["ma"] is None and r["rr"] == 0.0
    assert r["skip_rate"] == 1.0 and r["goal_coverage"] == 1.0


def test_kendall_tau_and_jaccard():
    assert M.kendall_tau_shared(list("abc"), list("abc")) == 1.0
    assert M.kendall_tau_shared(list("abc"), list("cba")) == -1.0
    assert M.kendall_tau_shared(list("abc"), list("acb")) == pytest.approx(1 / 3)
    assert M.kendall_tau_shared(["a"], ["a", "b"]) is None
    assert M.jaccard("ab", "bc") == pytest.approx(1 / 3) and M.jaccard([], []) == 1.0


def test_run_consistency():
    r = M.run_consistency([["a", "b"], ["a", "b"], ["a", "c"]])
    assert r["run_jaccard"] == pytest.approx(5 / 9)
    assert M.run_consistency([["a"]])["run_jaccard"] is None


def test_profile_sensitivity_hand_computed():
    mast = {"p1": {"a": 0, "b": 0}, "p2": {"a": .5, "b": 0}, "p3": {"a": 1, "b": 1}}
    paths = {"p1": ["a", "b"], "p2": ["a"], "p3": []}
    assert M.profile_sensitivity(mast, paths, ["a", "b"]) == pytest.approx(0.8660254, abs=1e-6)
    same = {"p1": ["a"], "p2": ["a"], "p3": ["a"]}
    assert M.profile_sensitivity(mast, same, ["a", "b"]) is None    # generic path -> undefined
