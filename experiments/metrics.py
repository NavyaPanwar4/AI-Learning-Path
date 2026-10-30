"""Automatic learning-path metrics (see paper Section 5.5).

A *path* is an ordered list of items ``{"skill_id", "action", "phase"}``.
Position in the sequence is the order of the list (phases flattened in order;
within a phase, listed order). A prerequisite counts as correctly placed only
if it appears strictly earlier in that sequence.

Notation
  R      closure of the goal's target skills in the SCORING graph
  m(s)   mastery in [0, 1]
  weak   skills with m < ``weak`` (default 0.50)
  strong skills with m >= ``strong`` (default 0.85) are 'mastered'
  need   max(0, strong - m)

Every metric returns None when its denominator is empty (the metric is
undefined for that unit) -- analysis scripts report how many units were
undefined instead of silently treating them as 0.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from app.services.path_planner import SkillGraph


@dataclass
class ScoreContext:
    graph: SkillGraph                 # scoring graph (graph E for the primary analysis)
    mastery: Mapping[str, float]
    targets: Sequence[str]
    weak: float = 0.50
    strong: float = 0.85
    k_frontier: int = 3

    def m(self, sid: str) -> float:
        return max(0.0, min(1.0, float(self.mastery.get(sid, 0.0))))


def _ratio(num: float, den: float) -> Optional[float]:
    return None if den == 0 else num / den


def dedupe_valid(path: Sequence[dict], graph: SkillGraph):
    """Return (valid ordered unique skill ids, n_invalid, n_duplicates)."""
    seen, ids, invalid, dup = set(), [], 0, 0
    for item in path:
        sid = item.get("skill_id")
        if sid not in graph.nodes:
            invalid += 1
        elif sid in seen:
            dup += 1
        else:
            seen.add(sid)
            ids.append(sid)
    return ids, invalid, dup


def score_path(path: Sequence[dict], ctx: ScoreContext) -> Dict[str, Optional[float]]:
    g = ctx.graph
    ids, n_invalid, n_dup = dedupe_valid(path, g)
    pos = {sid: i for i, sid in enumerate(ids)}
    in_path = set(ids)
    R = g.closure(ctx.targets)
    mastered_R = {s for s in R if ctx.m(s) >= ctx.strong}
    weak_R = {s for s in R if ctx.m(s) < ctx.weak}
    need = {s: max(0.0, ctx.strong - ctx.m(s)) for s in R}
    total_items = len(path)

    out: Dict[str, Optional[float]] = {}

    # --- 1. Prerequisite Violation Rate -----------------------------------
    pairs = order_v = omit_v = 0
    bad_skills = set()
    for s in ids:
        for u in g.direct_prereqs(s):
            if ctx.m(u) < ctx.strong:                    # unsatisfied prerequisite
                pairs += 1
                if u not in in_path:
                    omit_v += 1
                    bad_skills.add(s)
                elif pos[u] > pos[s]:
                    order_v += 1
                    bad_skills.add(s)
    out["pvr"] = _ratio(order_v + omit_v, pairs)
    out["pvr_order"] = _ratio(order_v, pairs)
    out["pvr_omit"] = _ratio(omit_v, pairs)
    out["pvr_pairs"] = float(pairs)
    out["pvr_any_violation"] = 1.0 if (order_v + omit_v) > 0 else (0.0 if pairs > 0 else None)

    # --- 2. Order Consistency (ancestor pairs) ----------------------------
    anc_pairs = ok = 0
    for a, b in itertools.permutations(ids, 2):
        if a in g.ancestors(b):
            anc_pairs += 1
            ok += pos[a] < pos[b]
    out["oc"] = _ratio(ok, anc_pairs)

    # --- 3. Weak-skill coverage ------------------------------------------
    out["wsc"] = _ratio(len(weak_R & in_path), len(weak_R))
    w_tot = sum(need[s] for s in weak_R)
    out["wsc_weighted"] = _ratio(sum(need[s] for s in weak_R & in_path), w_tot)

    # --- 4. Redundancy ----------------------------------------------------
    if not ids:
        out["rr"] = 0.0
        out["rr_hours"] = 0.0
    else:
        red = [s for s in ids if ctx.m(s) >= ctx.strong]
        out["rr"] = len(red) / len(ids)
        hrs = sum(g.nodes[s].hours for s in ids)
        out["rr_hours"] = _ratio(sum(g.nodes[s].hours for s in red), hrs)

    # --- 5. Mastery alignment (total-variation similarity) ----------------
    need_total = sum(need.values())
    if need_total == 0 or not ids:
        out["ma"] = None
    else:
        a = {s: 1.0 / len(ids) for s in ids}
        star = {s: need[s] / need_total for s in R}
        keys = set(a) | set(star)
        out["ma"] = 1.0 - 0.5 * sum(abs(a.get(s, 0.0) - star.get(s, 0.0)) for s in keys)

    # --- 6. Advancement ---------------------------------------------------
    out["skip_rate"] = _ratio(len(mastered_R - in_path), len(mastered_R))
    fringe = {s for s in R if ctx.m(s) < ctx.strong
              and all(ctx.m(u) >= ctx.strong for u in g.direct_prereqs(s))}
    head = ids[:ctx.k_frontier]
    out["frontier_at_k"] = _ratio(sum(1 for s in head if s in fringe), len(head)) if fringe else None

    # --- 7. Coverage / validity / size -----------------------------------
    out["goal_coverage"] = _ratio(len(mastered_R | (R & in_path)), len(R))
    tgt = set(ctx.targets)
    out["target_coverage"] = _ratio(sum(1 for t in tgt if t in in_path or t in mastered_R), len(tgt))
    out["off_goal_rate"] = _ratio(len(in_path - R), len(in_path))
    out["invalid_rate"] = _ratio(n_invalid, total_items)
    out["duplicate_rate"] = _ratio(n_dup, total_items)
    out["n_items"] = float(len(ids))
    out["hours"] = float(sum(g.nodes[s].hours for s in ids))
    out["n_needed"] = float(sum(1 for s in R if ctx.m(s) < ctx.strong))
    return out


# ---------------------------------------------------------------------------
# Cross-run / cross-profile metrics
# ---------------------------------------------------------------------------

def jaccard(a: Iterable, b: Iterable) -> Optional[float]:
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def kendall_tau_shared(seq_a: Sequence[str], seq_b: Sequence[str]) -> Optional[float]:
    """Kendall tau over skills present in both sequences (None if < 2 shared)."""
    shared = [s for s in seq_a if s in set(seq_b)]
    if len(shared) < 2:
        return None
    pb = {s: i for i, s in enumerate(seq_b)}
    conc = disc = 0
    for x, y in itertools.combinations(shared, 2):   # x before y in seq_a
        if pb[x] < pb[y]:
            conc += 1
        else:
            disc += 1
    return (conc - disc) / (conc + disc)


def run_consistency(paths: Sequence[Sequence[str]]) -> Dict[str, Optional[float]]:
    """Mean pairwise Jaccard (set) and Kendall tau (order) across repeated runs."""
    if len(paths) < 2:
        return {"run_jaccard": None, "run_tau": None}
    js, ts = [], []
    for a, b in itertools.combinations(paths, 2):
        js.append(jaccard(a, b))
        t = kendall_tau_shared(a, b)
        if t is not None:
            ts.append(t)
    return {"run_jaccard": sum(js) / len(js), "run_tau": (sum(ts) / len(ts)) if ts else None}


def spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    from scipy.stats import spearmanr
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    rho = spearmanr(x, y).statistic
    return None if (rho is None or math.isnan(rho)) else float(rho)


def profile_sensitivity(profile_masteries: Mapping[str, Mapping[str, float]],
                        profile_paths: Mapping[str, Sequence[str]],
                        skill_ids: Sequence[str]) -> Optional[float]:
    """Spearman correlation between pairwise mastery distance (L1 over
    ``skill_ids``) and pairwise path distance (1 - Jaccard of skill sets),
    across all pairs of profiles. A generic, learner-independent path gives ~0
    (or undefined when all paths are identical)."""
    ids = sorted(set(profile_masteries) & set(profile_paths))
    md, pd_ = [], []
    for a, b in itertools.combinations(ids, 2):
        md.append(sum(abs(profile_masteries[a].get(s, 0.0) - profile_masteries[b].get(s, 0.0)) for s in skill_ids))
        pd_.append(1.0 - jaccard(profile_paths[a], profile_paths[b]))
    return spearman(md, pd_)
