"""Robustness re-scoring of LOGGED paths (no LLM calls).

1. Graph perturbation: the logged paths were produced against graph P. Here they are re-scored against
   many randomly perturbed copies of P (edges dropped, or dropped and replaced by random edges), to ask
   whether the confirmatory conclusions depend on every edge of P being right. This does NOT replace an
   independently authored graph E; it only bounds how fragile the result is to graph errors.
2. Threshold sensitivity: re-score with different 'weak'/'mastered' thresholds. Logged D/B/C paths were
   planned with the original thresholds, and E's prompt used them, so only the *metrics* move.

  python -m experiments.sensitivity --logs experiments/results/groq__openai-gpt-oss-120b__test.jsonl \
         --out experiments/results/sensitivity_120b --draws 100

Everything here is exploratory. Confirmatory family per draw: {PVR, MA} x {A-D, E-D}, Holm over 4 tests.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from typing import Dict, List

import numpy as np

from app.services.path_planner import SkillGraph
from experiments import stats as S
from experiments.analyze import aggregate_units, read_logs, score_records
from experiments.graphs import DATA_DIR, load_goals, load_graph_p
from experiments.profiles import load_profiles


def perturb(raw_nodes, edges, order, frac, replace, rng) -> List[tuple]:
    edges = list(edges)
    k = int(round(frac * len(edges)))
    drop = set(rng.sample(range(len(edges)), k))
    kept = [e for i, e in enumerate(edges) if i not in drop]
    if replace:
        have = set(kept)
        rank = {s: i for i, s in enumerate(order)}
        ids = list(order)
        added = 0
        while added < k:
            u, v = rng.sample(ids, 2)
            if rank[u] > rank[v]:
                u, v = v, u
            if (u, v) not in have:          # always earlier->later in P's topological order: stays acyclic
                have.add((u, v)); kept.append((u, v)); added += 1
    return kept


def contrasts(rows, pids):
    units = aggregate_units(rows)
    out, ps = {}, []
    for m in ("pvr", "ma"):
        for x in ("A", "E"):
            xs = [units[(p, x)][m] if (p, x) in units else float("nan") for p in pids]
            ys = [units[(p, "D")][m] if (p, "D") in units else float("nan") for p in pids]
            res = S.paired_wilcoxon(xs, ys)
            out[(m, x)] = res
            ps.append(res["p"] if res["p"] is not None else 1.0)
    adj = S.holm(ps)
    for key, a in zip(list(out), adj):
        out[key]["holm"] = a
    return out


def summarise(draws: List[dict]):
    rows = []
    for key in draws[0]:
        diffs = [d[key]["mean_diff"] for d in draws if d[key]["mean_diff"] is not None]
        sig = [d[key]["holm"] < 0.05 for d in draws]
        rows.append({"contrast": f"{key[1]}-D", "metric": key[0], "draws": len(draws),
                     "median_diff": float(np.median(diffs)), "p05": float(np.percentile(diffs, 5)),
                     "p95": float(np.percentile(diffs, 95)), "share_holm_sig": float(np.mean(sig))})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--profiles-file", default=None)
    ap.add_argument("--draws", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)

    recs = [r for r in read_logs(a.logs) if r["split"] == a.split or a.split == "all"]
    graph_p, raw = load_graph_p()
    profiles = load_profiles(a.profiles_file or os.path.join(DATA_DIR, "profiles.json"))
    goals = load_goals()
    meta = json.load(open(a.logs[0].replace(".jsonl", ".meta.json")))["config"]
    weak, strong = meta["thresholds"]["weak"], meta["thresholds"]["strong"]
    pids = sorted({r["profile"] for r in recs})
    edges = [tuple(e) for e in raw["edges"]]
    order = graph_p.topological_order()
    os.makedirs(a.out, exist_ok=True)
    rng = random.Random(a.seed)
    out_rows = []

    base = contrasts(score_records(recs, graph_p, profiles, goals, weak, strong), pids)
    for (m, x), r in base.items():
        out_rows.append({"analysis": "baseline", "setting": "graph P", "contrast": f"{x}-D", "metric": m, "draws": 1,
                         "median_diff": r["mean_diff"], "p05": r["mean_diff"], "p95": r["mean_diff"],
                         "share_holm_sig": float(r["holm"] < 0.05)})

    for label, frac, replace in [("drop 10% of edges", .10, False), ("drop 20% of edges", .20, False),
                                 ("swap 10% of edges", .10, True), ("swap 20% of edges", .20, True),
                                 ("swap 30% of edges", .30, True)]:
        draws = []
        for _ in range(a.draws):
            g = SkillGraph(list(graph_p.nodes.values()), perturb(raw["nodes"], edges, order, frac, replace, rng))
            draws.append(contrasts(score_records(recs, g, profiles, goals, weak, strong), pids))
        for r in summarise(draws):
            out_rows.append({"analysis": "graph perturbation", "setting": label, **r})
        print("done", label, flush=True)

    for w, s in [(0.4, 0.80), (0.4, 0.90), (0.6, 0.80), (0.6, 0.90), (0.5, 0.80), (0.5, 0.90)]:
        res = contrasts(score_records(recs, graph_p, profiles, goals, w, s), pids)
        for (m, x), r in res.items():
            out_rows.append({"analysis": "thresholds", "setting": f"weak {w}, mastered {s}", "contrast": f"{x}-D",
                             "metric": m, "draws": 1, "median_diff": r["mean_diff"], "p05": r["mean_diff"],
                             "p95": r["mean_diff"], "share_holm_sig": float(r["holm"] < 0.05)})
    path = os.path.join(a.out, "sensitivity.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader(); w.writerows(out_rows)
    print("Wrote", path)


if __name__ == "__main__":
    main()
