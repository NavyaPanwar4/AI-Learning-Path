"""Compare condition A/E results across prompt wordings (v1 = main experiment, v2, v3).

  python -m experiments.prompt_robustness \
      --logs experiments/results/groq__openai-gpt-oss-120b__test.jsonl \
             experiments/results/groq__openai-gpt-oss-120b__test__prompt-v2.jsonl \
             experiments/results/groq__openai-gpt-oss-120b__test__prompt-v3.jsonl \
      --out experiments/results/prompt_robustness_120b.csv

Per variant and condition: mean PVR, MA, RR over profiles (profile = mean over goals and runs), the
A-E difference, and the parse-failure count. Exploratory; no confirmatory claims.
"""
import argparse, csv, json, os
import numpy as np
from experiments.analyze import aggregate_units, read_logs, score_records
from experiments.graphs import DATA_DIR, load_goals, load_graph_p
from experiments.profiles import load_profiles


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--profiles-file", default=None)
    a = ap.parse_args(argv)
    graph, _ = load_graph_p()
    profiles = load_profiles(a.profiles_file or os.path.join(DATA_DIR, "profiles.json"))
    goals = load_goals()
    rows_out = []
    for path in a.logs:
        meta = json.load(open(path.replace(".jsonl", ".meta.json")))
        variant = meta.get("prompt_variant", "v1")
        th = meta["config"]["thresholds"]
        recs = [r for r in read_logs([path]) if r["split"] == a.split]
        rows = score_records(recs, graph, profiles, goals, th["weak"], th["strong"])
        units = aggregate_units(rows)
        pids = sorted({p for p, _ in units})
        for c in ("A", "E", "C"):
            if not any((p, c) in units for p in pids):
                continue
            row = {"variant": variant, "condition": c,
                   "parse_failures": sum(1 for r in recs if r["condition"] == c and not r.get("parse_ok", True))}
            for m in ("pvr", "ma", "rr", "n_items"):
                vals = [units[(p, c)][m] for p in pids if (p, c) in units and units[(p, c)][m] == units[(p, c)][m]]
                row[m] = round(float(np.mean(vals)), 4) if vals else ""
            rows_out.append(row)
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0])); w.writeheader(); w.writerows(rows_out)
    for r in rows_out:
        print(r)


if __name__ == "__main__":
    main()
