"""Smoke/integrity tests for the experiment harness using the MOCK provider only."""
import csv
import json
import os

import pytest

from experiments import analyze, human_eval, run
from experiments.graphs import compare_graphs, load_goals, load_graph_e, load_graph_p
from experiments.profiles import depths, generate_profiles, load_profiles
from experiments.conditions import parse_path


def test_graph_p_and_goals_are_valid():
    g, raw = load_graph_p()
    assert len(g.nodes) == 40 and len(g.edges()) > 30
    for goal in load_goals():
        assert all(t in g.nodes for t in goal["targets"])
        assert len(g.closure(goal["targets"])) >= 5
    # edges are a transitive reduction: no edge implied by a longer path
    for u, v in g.edges():
        assert not any(w != u and u in g.ancestors(w) and w in g.ancestors(v) for w in g.nodes)


def test_graph_e_absent_returns_none_and_self_agreement_is_perfect():
    g, _ = load_graph_p()
    assert load_graph_e(g, "/nonexistent.csv") is None
    assert compare_graphs(g, g)["ancestor_kappa"] == 1.0


def test_profiles_are_seeded_and_mostly_prerequisite_consistent():
    g, raw = load_graph_p()
    tracks = {n["id"]: n["track"] for n in raw["nodes"]}
    a = generate_profiles(g, tracks)
    b = generate_profiles(g, tracks)
    assert a == b and len(a) == 27
    assert {p["split"] for p in a} == {"dev", "test"}
    shipped = load_profiles(os.path.join(os.path.dirname(run.__file__), "data", "profiles.json"))
    assert shipped == a                              # data file matches the generator
    for p in a:
        assert set(p["mastery"]) == set(g.nodes) and all(0 <= v <= 1 for v in p["mastery"].values())
    # non-edge archetypes: on average, deeper skills have lower mastery
    d = depths(g)
    for p in a:
        if p["archetype"] in ("beginner", "intermediate", "advanced"):
            shallow = [v for s, v in p["mastery"].items() if d[s] <= 1]
            deep = [v for s, v in p["mastery"].items() if d[s] >= 5]
            assert sum(shallow) / len(shallow) >= sum(deep) / len(deep)


def test_parse_path_variants():
    g, _ = load_graph_p()
    name = g.nodes["1"].name
    items = parse_path({"phases": [{"skills": [{"id": "1", "action": "learn"}, name, {"id": "999"}, "2"]}]}, g)
    assert [i["skill_id"] for i in items] == ["1", "1", None, "2"]
    assert parse_path({"nope": 1}, g) is None and parse_path(None, g) is None


@pytest.fixture(scope="module")
def mock_logs(tmp_path_factory):
    out = tmp_path_factory.mktemp("res")
    args = run.argparse.Namespace(provider="mock", model=None, split="all", conditions=None, goals=None,
                                  profile_ids="beg03,int03,une03,adv03,edg02,beg01", profiles_file=None,
                                  runs=2, config=None, out=str(out))
    path = run.run(args)
    return str(out), path


def test_runner_records_and_resume(mock_logs):
    out, path = mock_logs
    recs = [json.loads(l) for l in open(path)]
    assert recs and all(r["mock"] for r in recs)
    conds = {r["condition"] for r in recs}
    assert conds == {"A", "B", "C", "D", "E"}
    # 6 profiles x 3 goals = 18 units; A,E,C: 2 runs ; B,D: 1 run
    assert len(recs) == 18 * (2 * 3 + 2)
    # C is derived from A: its skills are a subset of A's valid skills for the same run
    by = {(r["profile"], r["goal"], r["condition"], r["run"]): r for r in recs}
    for (p, g, c, i), r in by.items():
        if c == "C":
            a_ids = {x["skill_id"] for x in by[(p, g, "A", i)]["path"] if x["skill_id"]}
            assert {x["skill_id"] for x in r["path"]} <= a_ids
    before = len(recs)
    args = run.argparse.Namespace(provider="mock", model=None, split="all", conditions=None, goals=None,
                                  profile_ids="beg03,int03,une03,adv03,edg02,beg01", profiles_file=None,
                                  runs=2, config=None, out=out)
    run.run(args)
    assert len([1 for _ in open(path)]) == before    # resumable: nothing duplicated


def test_planner_condition_has_no_violations_under_its_own_graph(mock_logs):
    out, path = mock_logs
    res = os.path.join(out, "an")
    r = analyze.analyze(run.argparse.Namespace(logs=[path], out=res, split="all", scoring_graph="P", weak=None,
                                               strong=None, seed=1, allow_mock=True))
    for (pid, cond), u in r["units"].items():
        if cond in ("B", "D") and u["pvr"] == u["pvr"]:          # not NaN
            assert u["pvr"] == 0.0
    for f in ("summary_by_condition.csv", "paired_tests.csv", "profile_sensitivity.csv", "run_consistency.csv",
              "generation_reliability.csv", "floor_ceiling.csv", "analysis_meta.json"):
        assert os.path.exists(os.path.join(res, f))
    assert json.load(open(os.path.join(res, "analysis_meta.json")))["banner"].startswith("MOCK")


def test_analysis_refuses_mock_by_default(mock_logs):
    out, path = mock_logs
    with pytest.raises(SystemExit):
        analyze.analyze(run.argparse.Namespace(logs=[path], out=os.path.join(out, "x"), split="all",
                                               scoring_graph="P", weak=None, strong=None, seed=1, allow_mock=False))


def test_human_eval_export_and_analyze_roundtrip(mock_logs, tmp_path):
    out, path = mock_logs
    d = str(tmp_path / "he")
    human_eval.main(["export", "--logs", path, "--out", d, "--per-archetype", "1", "--allow-mock"])
    key = json.load(open(os.path.join(d, "key.json")))
    text = open(os.path.join(d, "blinded_items.md")).read()
    assert len(key) > 3 and all(code in text for code in key)
    assert "condition" not in text.lower().replace("conditions", "")        # no leakage of condition labels
    rows = list(csv.DictReader(open(os.path.join(d, "rating_template.csv"))))
    import random
    rng = random.Random(0)
    for n in (1, 2):
        with open(os.path.join(d, f"r{n}.csv"), "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["item_code", *human_eval.DIMENSIONS])
            for r in rows:
                w.writerow([r["item_code"], *[rng.randint(1, 5) for _ in human_eval.DIMENSIONS]])
    human_eval.main(["analyze", "--dir", d, "--ratings", os.path.join(d, "r1.csv"), os.path.join(d, "r2.csv")])
    assert os.path.exists(os.path.join(d, "rater_agreement.csv")) and os.path.exists(os.path.join(d, "rating_summary.csv"))
