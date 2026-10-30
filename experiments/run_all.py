"""One-command Groq run: generate + analyse + bundle, for ONE model.

From the repository root (needs GROQ_API_KEY in .env):

    python -m experiments.run_all                                   # gpt-oss-120b, test split
    python -m experiments.run_all --model openai/gpt-oss-20b        # smaller-model run
    python -m experiments.run_all --split dev                       # optional dev pilot
    python -m experiments.run_all --split rep                       # replication set (57 new profiles)
    python -m experiments.run_all --prompt-variant v2               # paraphrased A/E prompts (A, E, C only)

Call settings (temperature, reasoning effort, max tokens, system prompt) come from
experiments/config.json, NOT from the app's .env, and are written to the *.meta.json
next to every log. Run it from a clean, tagged commit (git_dirty is recorded).
Resumable: re-run the same command after an interruption.
Output: experiments/results/RESULTS_<model>_<split>.zip  (send/keep this file).
"""
import argparse
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(HERE, "results")


def sh(*args):
    print("\n>>", " ".join(args), flush=True)
    r = subprocess.run([sys.executable, "-m", *args], cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"Step failed (exit {r.returncode}). Re-run the same command to resume.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/gpt-oss-120b")
    ap.add_argument("--split", choices=["dev", "test", "rep"], default="test")
    ap.add_argument("--prompt-variant", choices=["v1", "v2", "v3"], default="v1",
                    help="v1 = main prompts; v2/v3 = paraphrases (only A, E and C are run)")
    ap.add_argument("--scoring-graph", choices=["E", "P"], default=None,
                    help="default: E if experiments/data/graph_E_edges.csv exists, else P (circular)")
    a = ap.parse_args()

    sys.path.insert(0, ROOT)
    from app.utils.config import settings
    if not settings.GROQ_API_KEY:
        sys.exit("GROQ_API_KEY is not set (put it in .env).")
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    if dirty:
        print("WARNING: uncommitted changes; the log will record git_dirty=true. "
              "For the frozen rerun, commit and tag first.\n", flush=True)

    scoring = a.scoring_graph or ("E" if os.path.exists(os.path.join(HERE, "data", "graph_E_edges.csv")) else "P")
    extra = []
    if a.split == "rep":
        rep = os.path.join(HERE, "data", "profiles_rep.json")
        if not os.path.exists(rep):
            sh("experiments.make_rep_profiles")
        extra = ["--profiles-file", rep]
    run_extra = list(extra)
    if a.prompt_variant != "v1":
        run_extra += ["--prompt-variant", a.prompt_variant, "--conditions", "A,E,C"]
    sh("experiments.run", "--provider", "groq", "--model", a.model, "--split", a.split, *run_extra)
    stem = f"groq__{re.sub(r'[^A-Za-z0-9._-]+', '-', a.model)}__{a.split}"
    if a.prompt_variant != "v1":
        stem += f"__prompt-{a.prompt_variant}"
    out = os.path.join(RES, "analysis_" + stem)
    sh("experiments.analyze", "--logs", os.path.join(RES, stem + ".jsonl"), "--out", out,
       "--split", a.split, "--scoring-graph", scoring, *extra)

    bundle = os.path.join(RES, f"RESULTS_{stem}.zip")
    if a.split == "rep":                 # the profiles the logs refer to travel with them
        extra_files = [os.path.join(HERE, "data", "profiles_rep.json")]
    else:
        extra_files = []
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for path in (os.path.join(RES, stem + ".jsonl"), os.path.join(RES, stem + ".meta.json"), *extra_files):
            z.write(path, os.path.basename(path))
        for d, _, fs in os.walk(out):
            for f in fs:
                p = os.path.join(d, f)
                z.write(p, os.path.join(os.path.basename(out), os.path.relpath(p, out)))
    print(f"\nDONE (scoring graph: {scoring}). Keep/send this file:", bundle)


if __name__ == "__main__":
    main()
