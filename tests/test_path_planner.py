"""Hand-computed tests for app/services/path_planner.py (no DB, no LLM)."""
import pytest

from app.services.path_planner import (
    GraphError, PlannerConfig, SkillGraph, SkillNode, plan_path,
)


def make_graph():
    # a -> b -> d ; a -> c -> d ; d -> e ; x is unrelated
    nodes = [SkillNode(s, s.upper(), difficulty=d, hours=h) for s, d, h in
             [("a", 1, 10), ("b", 2, 20), ("c", 2, 5), ("d", 3, 30), ("e", 3, 15), ("x", 1, 1)]]
    edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "e")]
    return SkillGraph(nodes, edges)


def test_graph_rejects_cycle_unknown_and_selfloop():
    nodes = [SkillNode("a"), SkillNode("b")]
    with pytest.raises(GraphError):
        SkillGraph(nodes, [("a", "b"), ("b", "a")])
    with pytest.raises(GraphError):
        SkillGraph(nodes, [("a", "zzz")])
    with pytest.raises(GraphError):
        SkillGraph(nodes, [("a", "a")])


def test_ancestors_and_closure():
    g = make_graph()
    assert g.ancestors("e") == {"a", "b", "c", "d"}
    assert g.closure(["d"]) == {"a", "b", "c", "d"}
    assert g.is_ancestor("a", "e") and not g.is_ancestor("e", "a")


def test_topological_order_respects_edges_and_ties():
    g = make_graph()
    order = g.topological_order()
    for u, v in g.edges():
        assert order.index(u) < order.index(v)
    # tie between b and c (same difficulty 2) -> id order
    sub = g.topological_order(["a", "b", "c", "d"])
    assert sub == ["a", "b", "c", "d"]


def test_topological_order_uses_paths_through_excluded_nodes():
    g = make_graph()
    # b is excluded from the subset, but a must still precede d and e
    order = g.topological_order(["e", "d", "a"])
    assert order == ["a", "d", "e"]


def test_full_plan_beginner_learns_everything_in_order():
    g = make_graph()
    plan = plan_path(g, ["e"], {})  # all mastery 0
    assert plan.skill_ids() == ["a", "b", "c", "d", "e"]
    assert all(i.action == "learn" for i in plan.items)
    assert plan.skipped == []
    roles = {i.skill_id: i.role for i in plan.items}
    assert roles["e"] == "target" and roles["a"] == "prerequisite"


def test_mastered_skills_are_skipped_and_adequate_are_reviewed():
    g = make_graph()
    mastery = {"a": 0.95, "b": 0.60, "c": 0.90, "d": 0.10, "e": 0.0}
    plan = plan_path(g, ["e"], mastery)
    assert plan.skipped == ["a", "c"]                 # >= 0.85
    assert plan.skill_ids() == ["b", "d", "e"]
    actions = {i.skill_id: i.action for i in plan.items}
    assert actions == {"b": "review", "d": "learn", "e": "learn"}


def test_advanced_learner_gets_empty_plan():
    g = make_graph()
    plan = plan_path(g, ["e"], {s: 0.95 for s in g.nodes})
    assert plan.items == [] and set(plan.skipped) == {"a", "b", "c", "d", "e"}
    assert plan.phases == []


def test_inconsistent_profile_still_orders_prereqs_first():
    # d mastered but its prerequisite b is weak: b is still planned, before e
    g = make_graph()
    mastery = {"a": 0.9, "b": 0.1, "c": 0.9, "d": 0.9, "e": 0.0}
    plan = plan_path(g, ["e"], mastery)
    assert plan.skill_ids() == ["b", "e"]


def test_ablation_graph_only_ignores_mastery():
    g = make_graph()
    cfg = PlannerConfig(use_mastery=False)
    plan = plan_path(g, ["e"], {s: 0.99 for s in g.nodes}, cfg)
    assert plan.skill_ids() == ["a", "b", "c", "d", "e"]
    assert all(i.action == "learn" for i in plan.items)


def test_ablation_mastery_only_keeps_candidate_order_and_filters():
    g = make_graph()
    cfg = PlannerConfig(use_graph=False)
    cands = ["e", "d", "x", "a"]                       # deliberately wrong order
    mastery = {"e": 0.0, "d": 0.2, "x": 0.9, "a": 0.6}
    plan = plan_path(g, ["e"], mastery, cfg, candidates=cands)
    assert plan.skill_ids() == ["e", "d", "a"]         # order untouched, x skipped
    assert plan.skipped == ["x"]
    assert {i.skill_id: i.action for i in plan.items}["a"] == "review"


def test_phase_chunking_is_balanced_and_contiguous():
    nodes = [SkillNode(f"s{i}", hours=1) for i in range(10)]
    g = SkillGraph(nodes, [])
    cfg = PlannerConfig(items_per_phase=4, max_phases=7)
    plan = plan_path(g, [f"s{i}" for i in range(10)], {}, cfg)
    sizes = [len(p) for p in plan.phases]
    assert sum(sizes) == 10 and len(sizes) == 3 and max(sizes) - min(sizes) <= 1
    assert [i.phase_index for i in plan.items] == sorted(i.phase_index for i in plan.items)


def test_plan_is_deterministic():
    g = make_graph()
    m = {"a": 0.3, "b": 0.6, "c": 0.1}
    assert plan_path(g, ["e"], m).to_dict() == plan_path(g, ["e"], m).to_dict()


def test_unknown_target_raises():
    with pytest.raises(GraphError):
        plan_path(make_graph(), ["nope"], {})


def test_config_validation():
    with pytest.raises(ValueError):
        PlannerConfig(weak=0.9, strong=0.5)
