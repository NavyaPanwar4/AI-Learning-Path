"""Blinded human evaluation: export rating sheets, then analyse filled sheets.

  python -m experiments.human_eval export --logs <real log.jsonl> --out experiments/human_eval/round1
  # give blinded_items.md + rating_template.csv to each rater; KEEP key.json private
  python -m experiments.human_eval analyze --dir experiments/human_eval/round1 --ratings r1.csv r2.csv r3.csv

Rules fixed in advance (so selection cannot be tuned to results):
  * test-split profiles only, `--per-archetype` (profile, goal) units per archetype chosen by a seeded RNG;
  * one generation per condition: run 0;
  * all conditions rendered with the SAME template, neutral phase titles, items labelled Learn/Review
    (missing action -> Learn); skill names shown, ids hidden; item order randomised.
Raters score 1-5 on coherence, personalization, prerequisite_correctness, usefulness.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import defaultdict
from typing import Dict, List

import numpy as np

from experiments import stats as S
from experiments.graphs import DATA_DIR, load_goals, load_graph_p
from experiments.profiles import load_profiles

DIMENSIONS = ["coherence", "personalization", "prerequisite_correctness", "usefulness"]
RUBRIC = """RATING GUIDE (1-5, whole numbers)
coherence: Is the order logical and the grouping into phases sensible? 1 = confusing/illogical, 5 = fully logical.
personalization: Does the path fit THIS learner's mastery (skips what they know, focuses on gaps)? 1 = ignores the learner, 5 = tailored.
prerequisite_correctness: Is every skill placed after the skills it depends on, with needed prerequisites included? 1 = many errors, 5 = none.
usefulness: Would this path help this learner reach the goal? 1 = not useful, 5 = very useful.
Rate each item independently. You will not be told how any item was produced.
"""


def render_item(code, goal, mastery, targets, graph, path):
    R = sorted(graph.closure(targets), key=lambda s: (graph.nodes[s].difficulty, s))
    lines = [f"## Item {code}", f"**Goal:** {goal['name']}", "", "**Learner mastery (goal-relevant skills):**", ""]
    lines += [f"- {graph.nodes[s].name}: {round(100 * mastery[s])}%" for s in R]
    lines += ["", "**Proposed learning path:**", ""]
    phases = defaultdict(list)
    for it in path:
        if it.get("skill_id") in graph.nodes:
            phases[it["phase"]].append(it)
    if not phases:
        lines.append("(empty path - the learner needs nothing further for this goal)")
    for i, ph in enumerate(sorted(phases), 1):
        lines.append(f"Phase {i}")
        for it in phases[ph]:
            lines.append(f"  - {'Review' if it.get('action') == 'review' else 'Learn'}: {graph.nodes[it['skill_id']].name}")
    return "\n".join(lines) + "\n"


def export(args):
    graph, _ = load_graph_p()
    goals = {g["id"]: g for g in load_goals()}
    profiles = {p["id"]: p for p in load_profiles(os.path.join(DATA_DIR, "profiles.json"))}
    recs = []
    for p in args.logs:
        recs += [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    if any(r.get("mock") for r in recs) and not args.allow_mock:
        raise SystemExit("Refusing to export MOCK data for rating.")
    conds = args.conditions.split(",")
    by_key = {(r["profile"], r["goal"], r["condition"], r["run"]): r for r in recs}
    units = sorted({(r["profile"], r["goal"]) for r in recs if r["split"] == "test"})
    rng = random.Random(args.seed)
    by_arch = defaultdict(list)
    for pid, gid in units:
        by_arch[profiles[pid]["archetype"]].append((pid, gid))
    chosen = []
    for arch in sorted(by_arch):
        pool = by_arch[arch][:]
        rng.shuffle(pool)
        chosen += pool[:args.per_archetype]
    items = []
    for pid, gid in chosen:
        for c in conds:
            r = by_key.get((pid, gid, c, 0))
            if r is not None:
                items.append((pid, gid, c, r))
    rng.shuffle(items)
    os.makedirs(args.out, exist_ok=True)
    key, md = {}, [RUBRIC, ""]
    for n, (pid, gid, c, r) in enumerate(items, 1):
        code = f"I{n:03d}"
        key[code] = {"profile": pid, "goal": gid, "condition": c}
        md.append(render_item(code, goals[gid], profiles[pid]["mastery"], goals[gid]["targets"], graph, r["path"]))
    open(os.path.join(args.out, "blinded_items.md"), "w", encoding="utf-8").write("\n".join(md))
    json.dump(key, open(os.path.join(args.out, "key.json"), "w"), indent=1)
    with open(os.path.join(args.out, "rating_template.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["item_code", *DIMENSIONS])
        for code in key:
            w.writerow([code, "", "", "", ""])
    print(f"Exported {len(items)} items ({len(chosen)} units x {len(conds)} conditions) to {args.out}")


def analyze(args):
    key = json.load(open(os.path.join(args.dir, "key.json")))
    raters = []
    for p in args.ratings:
        d = {}
        for row in csv.DictReader(open(p, encoding="utf-8")):
            d[row["item_code"]] = {k: (float(row[k]) if row.get(k, "").strip() else None) for k in DIMENSIONS}
        raters.append(d)
    codes = sorted(key)
    out_rows, per_dim = [], {}
    for dim in DIMENSIONS:
        mat = [[r.get(c, {}).get(dim) for c in codes] for r in raters]
        per_dim[dim] = mat
        out_rows.append({"dimension": dim, "krippendorff_alpha_ordinal": S.krippendorff_alpha(mat, "ordinal"),
                         "n_raters": len(raters), "n_items": len(codes)})
    # item score = mean over raters; unit = (profile, condition) mean over goals
    unit = defaultdict(lambda: defaultdict(list))
    for dim in DIMENSIONS:
        for j, c in enumerate(codes):
            vals = [row[j] for row in per_dim[dim] if row[j] is not None]
            if vals:
                unit[(key[c]["profile"], key[c]["condition"])][dim].append(float(np.mean(vals)))
    conds = sorted({c for (_, c) in unit})
    pids = sorted({p for (p, _) in unit})
    summ, tests = [], []
    for dim in DIMENSIONS:
        for c in conds:
            v = [np.mean(unit[(p, c)][dim]) for p in pids if (p, c) in unit and unit[(p, c)][dim]]
            summ.append({"dimension": dim, "condition": c, "n_profiles": len(v),
                         "median": float(np.median(v)) if v else None, "mean": float(np.mean(v)) if v else None})
        for x, y in (("A", "D"), ("E", "D")):
            if x in conds and y in conds:
                xs = [np.mean(unit[(p, x)][dim]) if (p, x) in unit and unit[(p, x)][dim] else np.nan for p in pids]
                ys = [np.mean(unit[(p, y)][dim]) if (p, y) in unit and unit[(p, y)][dim] else np.nan for p in pids]
                t = S.paired_wilcoxon(xs, ys)
                tests.append({"dimension": dim, "contrast": f"{x} - {y}", **t})
    for t, a in zip([t for t in tests if t["p"] is not None], S.holm([t["p"] for t in tests if t["p"] is not None])):
        t["p_holm"] = a
    for name, rows in (("rater_agreement.csv", out_rows), ("rating_summary.csv", summ), ("rating_tests.csv", tests)):
        if rows:
            fields = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
            with open(os.path.join(args.dir, name), "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
    print("Wrote rater_agreement.csv, rating_summary.csv, rating_tests.csv to", args.dir)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--logs", nargs="+", required=True); e.add_argument("--out", required=True)
    e.add_argument("--conditions", default="A,E,D"); e.add_argument("--per-archetype", type=int, default=3)
    e.add_argument("--seed", type=int, default=7); e.add_argument("--allow-mock", action="store_true")
    a = sub.add_parser("analyze")
    a.add_argument("--dir", required=True); a.add_argument("--ratings", nargs="+", required=True)
    args = ap.parse_args(argv)
    export(args) if args.cmd == "export" else analyze(args)


if __name__ == "__main__":
    main()
