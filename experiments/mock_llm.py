"""Deterministic MOCK generator used ONLY to smoke-test the pipeline.

It imitates the *shape* of LLM outputs (with deliberate ordering errors and
redundant content) so that metrics/analysis code can be exercised without an
LLM. Mock results carry no scientific meaning; every log line is flagged
``mock: true`` and analyze.py refuses to treat them as results unless asked.
"""
from __future__ import annotations

import json
import random
from typing import Dict, List


def _phases(ids: List[str], rng: random.Random, titles=None) -> list:
    k = max(1, min(7, (len(ids) + 3) // 4)) if ids else 0
    out, size = [], (len(ids) // k + (1 if len(ids) % k else 0)) if k else 0
    for i in range(k):
        chunk = ids[i * size:(i + 1) * size]
        if chunk:
            out.append({"title": (titles or {}).get(i, f"Phase {i + 1}"),
                        "skills": [{"id": s, "action": "learn"} for s in chunk]})
    return out


def mock_generate(kind: str, ctx: Dict, seed: int) -> Dict:
    """kind in {"A","E","D"}; ctx has graph, mastery, targets, plan_phases."""
    rng = random.Random(seed)
    g, m, targets = ctx["graph"], ctx["mastery"], ctx["targets"]
    strong = ctx["strong"]
    R = g.closure(targets)
    if kind == "D":
        phases = []
        for ph in ctx["plan_phases"]:
            phases.append({"index": ph["index"], "title": f"Mock title {ph['index'] + 1}", "duration": "2 weeks",
                           "skills": [dict(sk) for sk in ph["skills"]]})
        return {"phases": phases}
    ordered = g.topological_order(R)
    if kind == "A":
        keep = [s for s in ordered if (m.get(s, 0) < strong and rng.random() < 0.8) or rng.random() < 0.35]
        swap_p = 0.25
    else:  # "E"
        keep = [s for s in ordered if m.get(s, 0) < strong and rng.random() < 0.92]
        swap_p = 0.05
    for i in range(len(keep) - 1):
        if rng.random() < swap_p:
            keep[i], keep[i + 1] = keep[i + 1], keep[i]
    return {"phases": _phases(keep, rng)}


def mock_response(kind: str, ctx: Dict, seed: int) -> Dict:
    parsed = mock_generate(kind, ctx, seed)
    return {"parsed": parsed, "raw": json.dumps(parsed), "provider": "mock", "model": "mock", "latency_s": 0.0}
