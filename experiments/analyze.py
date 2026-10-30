"""Score logged generations and run the pre-specified statistical analysis.

  python -m experiments.analyze --logs experiments/results/groq__openai-gpt-oss-120b__test.jsonl \
        --out experiments/results/analysis_gpt-oss-120b

Scoring graph: graph E (independently authored) when experiments/data/graph_E_edges.csv
has edges, otherwise graph P with a loud NOT-INDEPENDENT flag (circular for PVR/OC).
Mock logs are refused unless --allow-mock.

Unit of analysis = profile: metrics are averaged over goals and runs (NaN-aware)
within each (profile, condition). Confirmatory family (Holm over 4 tests):
  {PVR, MA} x {A vs D, E vs D}.  Everything else is exploratory.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np

from experiments import metrics as M
from experiments import stats as S
from experiments.graphs import DATA_DIR, compare_graphs, load_goals, load_graph_e, load_graph_p
from experiments.profiles import load_profiles

METRICS = ["pvr", "pvr_order", "pvr_omit", "pvr_any_violation", "oc", "wsc", "wsc_weighted", "rr", "rr_hours",
           "ma", "skip_rate", "frontier_at_k", "goal_coverage", "target_coverage", "off_goal_rate",
           "invalid_rate", "duplicate_rate", "n_items", "hours", "n_needed"]
PRIMARY = ["pvr", "ma"]
CONTRASTS = [("A", "D"), ("E", "D")]
EXPLORATORY_CONTRASTS = [("A", "E"), ("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]


def read_logs(paths: List[str]) -> List[dict]:
    recs = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            recs += [json.loads(line) for line in fh if line.strip()]
    return recs


def nanmean(vals):
    arr = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return float(np.mean(arr)) if arr else float("nan")


def score_records(recs, graph, profiles, goals, weak, strong):
    prof = {p["id"]: p for p in profiles}
    goal = {g["id"]: g for g in goals}
    rows = []
    for r in recs:
        if not r.get("parse_ok", True) and r["condition"] in ("A", "E", "D"):
            parse_fail = True
        else:
            parse_fail = False
        ctx = M.ScoreContext(graph, prof[r["profile"]]["mastery"], goal[r["goal"]]["targets"], weak, strong)
        row = {k: r[k] for k in ("profile", "archetype", "split", "goal", "condition", "run", "provider", "model")}
        row["parse_fail"] = parse_fail
        row.update(M.score_path(r["path"], ctx) if not parse_fail else {m: None for m in METRICS})
        row["_ids"] = [i["skill_id"] for i in r["path"] if i.get("skill_id")]
        rows.append(row)
    return rows


def aggregate_units(rows):
    """(profile, condition) -> metric -> nan-mean over goals and runs."""
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r["profile"], r["condition"])].append(r)
    units = {}
    for (pid, cond), rs in buckets.items():
        u = {m: nanmean([x[m] for x in rs]) for m in METRICS}
        u["archetype"] = rs[0]["archetype"]; u["split"] = rs[0]["split"]
        units[(pid, cond)] = u
    return units


def write_csv(path, rows, fields=None):
    if not rows:
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.items() if k in fields})


def analyze(args):
    recs = read_logs(args.logs)
    if any(r.get("mock") for r in recs) and not args.allow_mock:
        raise SystemExit("Refusing to analyse MOCK logs (pipeline smoke-test data). Use --allow-mock to override.")
    banner = "MOCK DATA - NOT RESULTS" if any(r.get("mock") for r in recs) else ""
    graph_p, _ = load_graph_p()
    graph_e = load_graph_e(graph_p)
    if args.scoring_graph == "P" or graph_e is None:
        scoring, tag = graph_p, ("P (NOT INDEPENDENT: circular for PVR/OC)" if args.scoring_graph != "P" else "P (requested)")
    else:
        scoring, tag = graph_e, "E (independent)"
    profiles = load_profiles(getattr(args, "profiles_file", None) or os.path.join(DATA_DIR, "profiles.json"))
    goals = load_goals()
    first = next(iter(recs))
    cfg_meta = {}
    meta_path = args.logs[0].replace(".jsonl", ".meta.json")
    if os.path.exists(meta_path):
        cfg_meta = json.load(open(meta_path))["config"]
    weak = args.weak if args.weak is not None else cfg_meta.get("thresholds", {}).get("weak", 0.5)
    strong = args.strong if args.strong is not None else cfg_meta.get("thresholds", {}).get("strong", 0.85)
    if args.split != "all":
        recs = [r for r in recs if r["split"] == args.split]

    rows = score_records(recs, scoring, profiles, goals, weak, strong)
    units = aggregate_units(rows)
    os.makedirs(args.out, exist_ok=True)
    conds = sorted({c for (_, c) in units})
    pids = sorted({p for (p, _) in units})

    # --- per-run scored rows -------------------------------------------------
    write_csv(os.path.join(args.out, "scored_runs.csv"),
              [{k: v for k, v in r.items() if k != "_ids"} for r in rows])

    # --- summary by condition -------------------------------------------------
    summary = []
    for c in conds:
        for m in METRICS:
            vals = [units[(p, c)][m] for p in pids if (p, c) in units]
            ok = [v for v in vals if not math.isnan(v)]
            summary.append({"condition": c, "metric": m, "n_profiles": len(vals), "n_defined": len(ok),
                            "mean": float(np.mean(ok)) if ok else None, "sd": float(np.std(ok, ddof=1)) if len(ok) > 1 else None,
                            "median": float(np.median(ok)) if ok else None})
    write_csv(os.path.join(args.out, "summary_by_condition.csv"), summary)

    # --- breakdown by archetype ----------------------------------------------
    arch_rows = []
    for c in conds:
        for arch in sorted({u["archetype"] for u in units.values()}):
            for m in ["pvr", "oc", "wsc", "rr", "ma", "skip_rate", "frontier_at_k", "goal_coverage", "n_items"]:
                vals = [units[(p, c)][m] for p in pids if (p, c) in units and units[(p, c)]["archetype"] == arch]
                arch_rows.append({"condition": c, "archetype": arch, "metric": m, "n": len(vals), "mean": nanmean(vals)})
    write_csv(os.path.join(args.out, "by_archetype.csv"), arch_rows)

    # --- paired tests ----------------------------------------------------------
    def col(c, m):
        return [units[(p, c)][m] if (p, c) in units else float("nan") for p in pids]

    tests = []
    for m in METRICS:
        for (x, y) in CONTRASTS + EXPLORATORY_CONTRASTS:
            if x not in conds or y not in conds:
                continue
            xs, ys = col(x, m), col(y, m)
            res = S.paired_wilcoxon(xs, ys)
            ci = S.bootstrap_ci_mean_diff(xs, ys, seed=args.seed)
            confirmatory = (m in PRIMARY and (x, y) in CONTRASTS)
            tests.append({"metric": m, "contrast": f"{x} - {y}", "confirmatory": confirmatory, "n": res["n"],
                          "mean_diff": res["mean_diff"], "ci_low": ci[0] if ci else None, "ci_high": ci[1] if ci else None,
                          "rank_biserial": res["rank_biserial"], "p": res["p"], "p_holm_confirmatory": None})
    conf = [t for t in tests if t["confirmatory"] and t["p"] is not None]
    for t, adj in zip(conf, S.holm([t["p"] for t in conf])):
        t["p_holm_confirmatory"] = adj
    write_csv(os.path.join(args.out, "paired_tests.csv"), tests)

    fr = []
    core = [c for c in ("A", "E", "D") if c in conds]
    for m in METRICS:
        if len(core) >= 3:
            r = S.friedman({c: col(c, m) for c in core})
            fr.append({"metric": m, "conditions": "+".join(core), **r})
    write_csv(os.path.join(args.out, "friedman.csv"), fr)

    # --- profile sensitivity (test profiles x goal x run) -------------------------
    prof = {p["id"]: p for p in profiles}
    skill_ids = sorted(scoring.nodes)
    ps_rows = []
    for c in conds:
        for g in goals:
            by_run = defaultdict(dict)
            for r in rows:
                if r["condition"] == c and r["goal"] == g["id"]:
                    by_run[r["run"]][r["profile"]] = r["_ids"]
            vals = []
            for run_i, paths in by_run.items():
                v = M.profile_sensitivity({p: prof[p]["mastery"] for p in paths}, paths, skill_ids)
                if v is not None:
                    vals.append(v)
            ps_rows.append({"condition": c, "goal": g["id"], "n_runs": len(by_run),
                            "profile_sensitivity": float(np.mean(vals)) if vals else None})
    write_csv(os.path.join(args.out, "profile_sensitivity.csv"), ps_rows)

    # --- run-to-run consistency (A, E, C have several runs) ------------------------------
    rc = []
    group = defaultdict(list)
    for r in rows:
        group[(r["condition"], r["profile"], r["goal"])].append(r["_ids"])
    for c in conds:
        js, ts = [], []
        for (cc, p, g), paths in group.items():
            if cc == c and len(paths) > 1:
                x = M.run_consistency(paths)
                if x["run_jaccard"] is not None:
                    js.append(x["run_jaccard"])
                if x["run_tau"] is not None:
                    ts.append(x["run_tau"])
        rc.append({"condition": c, "units": len(js), "mean_run_jaccard": float(np.mean(js)) if js else None,
                   "mean_run_tau": float(np.mean(ts)) if ts else None})
    write_csv(os.path.join(args.out, "run_consistency.csv"), rc)

    # --- generation reliability ----------------------------------------------------------
    rel = []
    for c in conds:
        rr = [r for r in recs if r["condition"] == c]
        rel.append({"condition": c, "n": len(rr), "parse_failures": sum(1 for r in rr if not r.get("parse_ok", True)),
                    "mean_attempts": float(np.mean([r.get("attempts", 0) for r in rr])) if rr else None,
                    "mean_latency_s": float(np.mean([r.get("latency_s", 0) or 0 for r in rr])) if rr else None,
                    "mean_adherence": nanmean([r.get("adherence") for r in rr if r.get("adherence") is not None]) if c == "D" else None})
    write_csv(os.path.join(args.out, "generation_reliability.csv"), rel)

    # --- floor / ceiling diagnostics ----------------------------------------------------------
    diag = []
    for c in conds:
        vals = [units[(p, c)]["pvr"] for p in pids if (p, c) in units]
        ok = [v for v in vals if not math.isnan(v)]
        diag.append({"condition": c, "pvr_defined": len(ok), "pvr_zero_share": (sum(1 for v in ok if v == 0.0) / len(ok)) if ok else None})
    write_csv(os.path.join(args.out, "floor_ceiling.csv"), diag)

    # --- graph agreement (if E exists) ----------------------------------------------------------------
    agreement = compare_graphs(graph_p, graph_e) if graph_e is not None else None

    with open(os.path.join(args.out, "analysis_meta.json"), "w") as fh:
        json.dump({"banner": banner, "scoring_graph": tag, "weak": weak, "strong": strong, "split": args.split,
                   "n_profiles": len(pids), "conditions": conds, "graph_agreement_P_vs_E": agreement,
                   "logs": args.logs}, fh, indent=1)
    print(f"{banner or 'REAL DATA'} | scoring graph: {tag} | profiles: {len(pids)} | conditions: {conds}")
    print("Outputs in", args.out)
    return {"units": units, "tests": tests}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", choices=["dev", "test", "rep", "all"], default="test")
    ap.add_argument("--profiles-file", default=None, help="profiles JSON used for the logs (default data/profiles.json)")
    ap.add_argument("--scoring-graph", choices=["E", "P"], default="E")
    ap.add_argument("--weak", type=float, default=None)
    ap.add_argument("--strong", type=float, default=None)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--allow-mock", action="store_true")
    analyze(ap.parse_args(argv))


if __name__ == "__main__":
    main()
