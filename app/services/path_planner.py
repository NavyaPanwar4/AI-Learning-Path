"""Deterministic, prerequisite-aware, mastery-aware learning-path planner.

This module is pure Python (standard library only) so that it can be

* used by the production roadmap service behind a feature flag
  (``USE_PATH_PLANNER``), and
* imported unchanged by the research experiment harness in ``experiments/``.

What it does
------------
Given a prerequisite graph, a set of goal (target) skills and a mastery value
per skill, it decides *which* skills belong in a learning path, *in what
order*, and with *which action* (``learn`` / ``review``). It does not call an
LLM. The LLM's job (see ``llm_service.generate_roadmap_from_plan``) is only to
elaborate the plan (titles, durations, resources, projects).

Rules (R1-R4; they are the "adaptation engine" described in the paper)
----------------------------------------------------------------------
R1  Prerequisite closure: every ancestor of a target skill is a candidate.
R2  Topological ordering: a skill is never placed before its prerequisites.
R3  Compression: a candidate whose mastery >= ``strong`` is excluded from
    instruction (reported in ``Plan.skipped``).
R4  Remediation emphasis: mastery < ``weak`` -> action ``learn``;
    ``weak`` <= mastery < ``strong`` -> action ``review``.

Ablation flags
--------------
``use_graph=False``  -> no closure and no topological ordering; the candidate
                        list (and its order) must be supplied by the caller.
``use_mastery=False``-> mastery is ignored; every candidate is ``learn``.

Mastery is on a 0-1 scale. Defaults mirror the thresholds in
``adaptive_service`` (weak 50%, strong 85%).
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

WEAK_DEFAULT = 0.50
STRONG_DEFAULT = 0.85

ACTION_LEARN = "learn"
ACTION_REVIEW = "review"


class GraphError(ValueError):
    """Raised for malformed prerequisite graphs (unknown ids, cycles)."""


@dataclass(frozen=True)
class SkillNode:
    skill_id: str
    name: str = ""
    difficulty: int = 1          # 1 beginner, 2 intermediate, 3 advanced
    hours: float = 1.0           # estimated learning hours


class SkillGraph:
    """Directed acyclic prerequisite graph.

    An edge ``(u, v)`` means *u is a direct prerequisite of v*.
    """

    def __init__(self, nodes: Iterable[SkillNode], edges: Iterable[Tuple[str, str]]):
        self.nodes: Dict[str, SkillNode] = {}
        for node in nodes:
            if node.skill_id in self.nodes:
                raise GraphError(f"Duplicate skill id: {node.skill_id}")
            self.nodes[node.skill_id] = node

        self._prereqs: Dict[str, Set[str]] = {sid: set() for sid in self.nodes}
        self._dependents: Dict[str, Set[str]] = {sid: set() for sid in self.nodes}
        for u, v in edges:
            if u not in self.nodes or v not in self.nodes:
                raise GraphError(f"Edge ({u!r} -> {v!r}) references an unknown skill id")
            if u == v:
                raise GraphError(f"Self-loop on {u!r}")
            self._prereqs[v].add(u)
            self._dependents[u].add(v)

        self._check_acyclic()
        self._ancestor_cache: Dict[str, frozenset] = {}

    # ------------------------------------------------------------------
    def _check_acyclic(self) -> None:
        indeg = {sid: len(p) for sid, p in self._prereqs.items()}
        queue = [sid for sid, d in indeg.items() if d == 0]
        seen = 0
        while queue:
            cur = queue.pop()
            seen += 1
            for nxt in self._dependents[cur]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        if seen != len(self.nodes):
            raise GraphError("Prerequisite graph contains a cycle")

    # ------------------------------------------------------------------
    def direct_prereqs(self, skill_id: str) -> frozenset:
        return frozenset(self._prereqs[skill_id])

    def edges(self) -> List[Tuple[str, str]]:
        return sorted((u, v) for v, ps in self._prereqs.items() for u in ps)

    def ancestors(self, skill_id: str) -> frozenset:
        """All transitive prerequisites of ``skill_id`` (excluding itself)."""
        cached = self._ancestor_cache.get(skill_id)
        if cached is not None:
            return cached
        out: Set[str] = set()
        stack = list(self._prereqs[skill_id])
        while stack:
            cur = stack.pop()
            if cur in out:
                continue
            out.add(cur)
            stack.extend(self._prereqs[cur])
        result = frozenset(out)
        self._ancestor_cache[skill_id] = result
        return result

    def closure(self, targets: Iterable[str]) -> Set[str]:
        """Targets together with all their transitive prerequisites."""
        out: Set[str] = set()
        for t in targets:
            if t not in self.nodes:
                raise GraphError(f"Unknown target skill id: {t!r}")
            out.add(t)
            out |= self.ancestors(t)
        return out

    def is_ancestor(self, a: str, b: str) -> bool:
        return a in self.ancestors(b)

    def topological_order(self, subset: Optional[Iterable[str]] = None, key=None) -> List[str]:
        """Deterministic topological order of ``subset`` (default: all nodes).

        The order is computed over the full induced reachability, i.e. if
        ``a`` is an ancestor of ``b`` then ``a`` precedes ``b`` even when the
        connecting skills are not in ``subset``. ``key(skill_id)`` breaks ties
        (lowest first); default is ``(difficulty, skill_id)``.
        """
        ids = set(self.nodes) if subset is None else set(subset)
        key = key or (lambda sid: (self.nodes[sid].difficulty, sid))
        # Work on the closure so that paths through excluded nodes still order
        # included nodes correctly, then filter.
        universe = self.closure(ids)
        indeg = {sid: len(self._prereqs[sid] & universe) for sid in universe}
        heap = [(key(sid), sid) for sid, d in indeg.items() if d == 0]
        heapq.heapify(heap)
        order: List[str] = []
        while heap:
            _, cur = heapq.heappop(heap)
            order.append(cur)
            for nxt in self._dependents[cur]:
                if nxt in universe:
                    indeg[nxt] -= 1
                    if indeg[nxt] == 0:
                        heapq.heappush(heap, (key(nxt), nxt))
        return [sid for sid in order if sid in ids]


# ----------------------------------------------------------------------
# Planner
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerConfig:
    weak: float = WEAK_DEFAULT
    strong: float = STRONG_DEFAULT
    use_graph: bool = True
    use_mastery: bool = True
    items_per_phase: int = 4
    min_phases: int = 1
    max_phases: int = 7

    def __post_init__(self):
        if not 0.0 <= self.weak < self.strong <= 1.0:
            raise ValueError("Require 0 <= weak < strong <= 1")
        if self.items_per_phase < 1 or self.min_phases < 1 or self.max_phases < self.min_phases:
            raise ValueError("Invalid phase configuration")


@dataclass
class PlanItem:
    skill_id: str
    name: str
    action: str                 # "learn" | "review"
    phase_index: int
    hours: float
    role: str                   # "target" | "prerequisite" | "candidate"
    mastery: float


@dataclass
class Plan:
    items: List[PlanItem] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)   # candidate ids excluded as mastered
    config: Optional[PlannerConfig] = None

    @property
    def phases(self) -> List[List[PlanItem]]:
        n = 0 if not self.items else max(i.phase_index for i in self.items) + 1
        out: List[List[PlanItem]] = [[] for _ in range(n)]
        for item in self.items:
            out[item.phase_index].append(item)
        return out

    def skill_ids(self) -> List[str]:
        return [i.skill_id for i in self.items]

    def to_path(self) -> dict:
        """Neutral path structure shared with the experiment metrics."""
        return {
            "phases": [
                {"title": "", "items": [{"skill_id": i.skill_id, "action": i.action} for i in phase]}
                for phase in self.phases
            ]
        }

    def to_dict(self) -> dict:
        return {
            "items": [vars(i).copy() for i in self.items],
            "skipped": list(self.skipped),
        }


def _chunk_sizes(n: int, config: PlannerConfig) -> List[int]:
    if n == 0:
        return []
    phases = min(max(math.ceil(n / config.items_per_phase), config.min_phases), config.max_phases)
    phases = min(phases, n)
    base, extra = divmod(n, phases)
    return [base + (1 if i < extra else 0) for i in range(phases)]


def plan_path(
    graph: SkillGraph,
    targets: Sequence[str],
    mastery: Mapping[str, float],
    config: Optional[PlannerConfig] = None,
    candidates: Optional[Sequence[str]] = None,
) -> Plan:
    """Build an ordered, phased plan. Pure and deterministic.

    ``mastery`` maps skill id -> [0, 1]; missing skills count as 0.0.
    ``candidates`` is used only when ``config.use_graph`` is False: it is the
    ordered list of skills to filter (e.g. an LLM-proposed list). If omitted
    the targets themselves are used.
    """
    cfg = config or PlannerConfig()
    targets = list(dict.fromkeys(targets))
    target_set = set(targets)
    for t in targets:
        if t not in graph.nodes:
            raise GraphError(f"Unknown target skill id: {t!r}")

    def m_of(sid: str) -> float:
        return max(0.0, min(1.0, float(mastery.get(sid, 0.0))))

    # --- candidate set and order -------------------------------------
    if cfg.use_graph:
        candidate_ids = graph.closure(targets)
        if cfg.use_mastery:
            def key(sid: str):
                node = graph.nodes[sid]
                return (node.difficulty, -(cfg.strong - m_of(sid)), sid)
        else:
            def key(sid: str):
                return (graph.nodes[sid].difficulty, sid)
        ordered = graph.topological_order(candidate_ids, key=key)
    else:
        ordered = list(dict.fromkeys(candidates if candidates is not None else targets))
        for sid in ordered:
            if sid not in graph.nodes:
                raise GraphError(f"Unknown candidate skill id: {sid!r}")

    # --- mastery filter and actions ----------------------------------
    kept: List[Tuple[str, str]] = []
    skipped: List[str] = []
    for sid in ordered:
        if not cfg.use_mastery:
            kept.append((sid, ACTION_LEARN))
            continue
        m = m_of(sid)
        if m >= cfg.strong:
            skipped.append(sid)
        elif m < cfg.weak:
            kept.append((sid, ACTION_LEARN))
        else:
            kept.append((sid, ACTION_REVIEW))

    # --- phases -------------------------------------------------------
    items: List[PlanItem] = []
    pos = 0
    for phase_index, size in enumerate(_chunk_sizes(len(kept), cfg)):
        for sid, action in kept[pos:pos + size]:
            node = graph.nodes[sid]
            items.append(PlanItem(
                skill_id=sid,
                name=node.name or sid,
                action=action,
                phase_index=phase_index,
                hours=node.hours,
                role="target" if sid in target_set else ("prerequisite" if cfg.use_graph else "candidate"),
                mastery=m_of(sid),
            ))
        pos += size
    return Plan(items=items, skipped=skipped, config=cfg)
