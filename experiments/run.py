"""Experiment runner: generates and LOGS learning paths for every
(profile, goal, condition, run). Scoring is done later by analyze.py so a log
can be re-scored with a different graph/threshold without re-running the LLM.

Examples (from the repository root):
  python -m experiments.run --provider mock --split dev          # pipeline smoke test only
  python -m experiments.run --provider groq --split dev
  python -m experiments.run --provider groq   --split test
Runs are resumable: existing keys in the output JSONL are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zlib
from typing import Dict, List, Optional

from experiments import conditions as C
from experiments.graphs import DATA_DIR, load_goals, load_graph_p
from experiments.mock_llm import mock_response
from experiments.profiles import load_profiles

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config(path: Optional[str] = None) -> dict:
    with open(path or os.path.join(HERE, "config.json"), encoding="utf-8") as fh:
        return json.load(fh)


def file_hash(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def make_seed(base: int, *parts) -> int:
    return (zlib.crc32("|".join(map(str, (base, *parts))).encode()) ^ base) & 0x7FFFFFFF


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def git_commit() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              cwd=os.path.dirname(HERE), timeout=5).stdout.strip() or None
    except Exception:
        return None


def git_dirty() -> Optional[bool]:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                             cwd=os.path.dirname(HERE), timeout=10)
        return bool(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:
        return None


class Generator:
    """One strict LLM call with fresh-sample retry on parse failure (no repair prompt)."""

    def __init__(self, provider: str, model: Optional[str], cfg: dict):
        self.provider, self.cfg = provider, cfg
        self.model = model or ("mock" if provider == "mock" else cfg["models"][provider])
        if provider != "mock":
            from app.services.llm_service import llm_service
            self.svc = llm_service

    def __call__(self, kind: str, prompt: str, ctx: dict, seed: int):
        attempts, resp = 0, None
        for attempt in range(self.cfg["max_attempts"]):
            attempts += 1
            s = seed + 1000 * attempt
            if self.provider == "mock":
                resp = mock_response(kind, ctx, s)
            else:
                resp = self.svc.generate_experiment_json(
                    prompt, provider=self.provider, model=self.model,
                    temperature=self.cfg["temperature"], seed=s,
                    system_prompt=self.cfg["groq_call"]["system_prompt"],
                    max_tokens=self.cfg["groq_call"]["max_completion_tokens"],
                    reasoning_effort=(self.cfg["groq_call"].get("qwen_reasoning_effort", "none") if self.model.startswith("qwen/")
                                      else self.cfg["groq_call"]["reasoning_effort"]))
            if isinstance(resp.get("parsed"), dict) and isinstance(resp["parsed"].get("phases"), list):
                break
        return resp, attempts


def run(args) -> str:
    cfg = load_config(args.config)
    variant = getattr(args, "prompt_variant", "v1")
    if args.runs:
        cfg["runs"] = args.runs
    graph, raw_graph = load_graph_p()
    goals = {g["id"]: g for g in load_goals()}
    profiles = load_profiles(args.profiles_file or os.path.join(DATA_DIR, "profiles.json"))
    if args.split != "all":
        profiles = [p for p in profiles if p["split"] == args.split]
    if args.profile_ids:
        wanted = set(args.profile_ids.split(","))
        profiles = [p for p in profiles if p["id"] in wanted]
    goal_ids = args.goals.split(",") if args.goals else list(goals)
    conds = args.conditions.split(",") if args.conditions else cfg["conditions"]
    weak, strong = cfg["thresholds"]["weak"], cfg["thresholds"]["strong"]

    gen = Generator(args.provider, args.model, cfg)
    os.makedirs(args.out, exist_ok=True)
    stem = f"{args.provider}__{safe(gen.model)}__{args.split}" + ("" if variant == "v1" else f"__prompt-{variant}")
    log_path = os.path.join(args.out, stem + ".jsonl")
    done, existing = set(), {}
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec_ = json.loads(line)
                    done.add(rec_["key"]); existing[rec_["key"]] = rec_
    meta = {
        "provider": args.provider, "model": gen.model, "mock": args.provider == "mock",
        "config": cfg, "split": args.split, "git_commit": git_commit(),
        "git_dirty": git_dirty(), "prompt_variant": variant,
        "call_settings": {"temperature": cfg["temperature"], **cfg["groq_call"],
                          **({} if gen.model.startswith("openai/gpt-oss")
                             else {"reasoning_effort": cfg["groq_call"].get("qwen_reasoning_effort", "none"),
                                   "reasoning_format": "hidden"} if gen.model.startswith("qwen/")
                             else {"reasoning_effort": "not sent (non-reasoning model)"}),
                          "seed": "per call (see each record)", "json_mode": "prompt-level JSON instruction; parsed locally"},
        "graph_P_hash": file_hash(os.path.join(DATA_DIR, "graph_P.json")),
        "profiles_hash": file_hash(args.profiles_file or os.path.join(DATA_DIR, "profiles.json")),
        "python": sys.version.split()[0], "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(os.path.join(args.out, stem + ".meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)

    n_new = 0
    with open(log_path, "a", encoding="utf-8") as out:
        def emit(rec: dict):
            nonlocal n_new
            if rec["key"] in done:
                return
            out.write(json.dumps(rec) + "\n"); out.flush(); done.add(rec["key"]); n_new += 1

        for prof in profiles:
            mastery = prof["mastery"]
            for gid in goal_ids:
                goal = goals[gid]
                targets = goal["targets"]
                base_ctx = {"graph": graph, "mastery": mastery, "targets": targets, "strong": strong}
                plan_d = C.planner_plan(graph, targets, mastery, weak, strong, items_per_phase=cfg["items_per_phase"])
                plan_b = C.planner_plan(graph, targets, mastery, weak, strong, use_mastery=False,
                                        items_per_phase=cfg["items_per_phase"])
                for run_i in range(cfg["runs"]):
                    base = {"profile": prof["id"], "archetype": prof["archetype"], "split": prof["split"],
                            "goal": gid, "run": run_i, "provider": args.provider, "model": gen.model,
                            "mock": args.provider == "mock"}
                    a_items = None
                    for cond in conds:
                        key = f'{prof["id"]}|{gid}|{cond}|{run_i}'
                        if key in done:
                            if cond == "A":           # resume: reuse the logged A output so C can still be derived
                                a_items = existing[key]["path"] if existing[key].get("parse_ok") else None
                            continue
                        seed = make_seed(cfg["seed"], prof["id"], gid, cond, run_i)
                        rec = dict(base, key=key, condition=cond, seed=seed)
                        if cond in ("A", "E"):
                            prompt = (C.prompt_a(goal["name"], graph, targets, mastery, cfg["max_phases"], variant=variant) if cond == "A"
                                      else C.prompt_e(goal["name"], graph, targets, mastery, weak, strong, cfg["max_phases"], variant=variant))
                            resp, attempts = gen(cond, prompt, base_ctx, seed)
                            items = C.parse_path(resp["parsed"], graph)
                            rec.update(prompt_hash=C.prompt_hash(prompt), attempts=attempts, raw=resp["raw"],
                                       latency_s=resp["latency_s"], parse_ok=items is not None, path=items or [])
                            if cond == "A":
                                a_items = items
                        elif cond == "D":
                            if run_i >= cfg["d_llm_runs"]:
                                continue              # structure is deterministic; one LLM elaboration is enough
                            phases = C.plan_phases_for_prompt(plan_d)
                            prompt = C.prompt_d(phases, goal["name"])
                            resp, attempts = gen("D", prompt, dict(base_ctx, plan_phases=phases), seed) if phases else ({"raw": "", "parsed": None, "latency_s": 0.0}, 0)
                            merged = LLMmerge(phases, resp["parsed"])
                            rec.update(prompt_hash=C.prompt_hash(prompt), attempts=attempts, raw=resp["raw"],
                                       latency_s=resp["latency_s"], parse_ok=(not phases) or resp["parsed"] is not None,   # nothing to elaborate -> not a failure
                                       adherence=merged["adherence"], titles=[p["title"] for p in merged["phases"]],
                                       path=C.plan_to_items(plan_d), skipped=plan_d.skipped)
                        elif cond == "B":
                            if run_i > 0:
                                continue
                            rec.update(attempts=0, parse_ok=True, path=C.plan_to_items(plan_b), skipped=plan_b.skipped)
                        elif cond == "C":
                            if not isinstance(a_items, list):
                                continue              # needs a fresh A output from this same loop
                            cands = []
                            for it in a_items:
                                if it["skill_id"] in graph.nodes and it["skill_id"] not in cands:
                                    cands.append(it["skill_id"])
                            plan_c = C.planner_plan(graph, targets, mastery, weak, strong, use_graph=False,
                                                    candidates=cands, items_per_phase=cfg["items_per_phase"])
                            rec.update(attempts=0, parse_ok=True, path=C.plan_to_items(plan_c), skipped=plan_c.skipped)
                        else:
                            raise SystemExit(f"Unknown condition {cond!r}")
                        emit(rec)
            print(f"[{prof['id']}] done ({n_new} new records so far)", flush=True)
    print(f"Wrote {n_new} new records to {log_path}")
    return log_path


def LLMmerge(plan_phases, parsed):
    from app.services.llm_service import LLMService
    return LLMService.merge_elaboration_with_plan(plan_phases, parsed)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["groq", "mock"], required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--split", choices=["dev", "test", "rep", "all"], default="dev")
    ap.add_argument("--prompt-variant", choices=["v1", "v2", "v3"], default="v1",
                    help="v1 = main experiments; v2/v3 = paraphrased A/E prompts (robustness check)")
    ap.add_argument("--conditions", default=None, help="comma list, default from config")
    ap.add_argument("--goals", default=None)
    ap.add_argument("--profile-ids", default=None)
    ap.add_argument("--profiles-file", default=None)
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    run(ap.parse_args(argv))


if __name__ == "__main__":
    main()
