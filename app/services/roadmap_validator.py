"""Deterministic validation and repair for LLM-proposed learning roadmaps.

This module does not choose a roadmap up front. It validates an LLM proposal
against the known skill catalogue, the target skills, learner mastery, and the
configured prerequisite graph. The graph remains an assumption: this validator
cannot establish that the graph itself is pedagogically correct.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional

from app.services.path_planner import GraphError, SkillGraph


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _mastery_value(mastery: Mapping[str, float], skill_id: str) -> float:
    try:
        return max(0.0, min(1.0, float(mastery.get(skill_id, 0.0))))
    except (TypeError, ValueError):
        return 0.0


def validate_llm_roadmap_proposal(
    proposal: Optional[dict],
    graph: SkillGraph,
    target_ids: Iterable[str],
    mastery: Mapping[str, float],
    *,
    weak_threshold: float = 0.50,
    strong_threshold: float = 0.85,
) -> dict:
    """Normalize and repair an LLM roadmap proposal.

    Returned shape::

        {
          "plan_phases": [{"index", "title", "skills": [{"id", "name", "action"}]}],
          "repaired": bool,
          "issues": [str, ...],
        }

    Only skills in the target skills' prerequisite closure are allowed. Every
    unmastered candidate in that closure is required; mastered skills are
    excluded. The LLM's order is retained whenever it respects prerequisite
    constraints. When it does not, a stable topological ordering is computed,
    preferring the LLM's relative order among currently eligible skills.
    """
    if not 0.0 <= weak_threshold < strong_threshold <= 1.0:
        raise ValueError("Require 0 <= weak_threshold < strong_threshold <= 1")

    targets = list(dict.fromkeys(str(sid) for sid in target_ids if str(sid) in graph.nodes))
    if not targets:
        raise GraphError("Cannot validate a roadmap without valid target skills")

    allowed_ids = graph.closure(targets)
    required_ids = {
        sid for sid in allowed_ids
        if _mastery_value(mastery, sid) < strong_threshold
    }

    # Exact ID is preferred. Exact normalized names are accepted as a recovery
    # path for model outputs that accidentally place a name in the id field.
    name_to_id: Dict[str, str] = {}
    for sid in allowed_ids:
        name_to_id[_key(graph.nodes[sid].name)] = sid

    phases = (proposal or {}).get("phases", []) if isinstance(proposal, dict) else []
    if not isinstance(phases, list):
        phases = []

    issues = []
    repaired = False
    observed_order = []
    first_phase_by_skill: Dict[str, int] = {}
    original_phase_by_skill: Dict[str, int] = {}
    phase_metadata: Dict[int, dict] = {}

    for position, phase in enumerate(phases):
        if not isinstance(phase, dict):
            issues.append(f"Ignored malformed phase at position {position}")
            repaired = True
            continue
        raw_index = phase.get("index", position)
        phase_index = raw_index if isinstance(raw_index, int) and raw_index >= 0 else position
        if phase_index != position:
            # Index normalization alone does not change the learning plan's
            # skill structure. Do not force a fresh LLM elaboration solely
            # because the model returned 1-based (or otherwise non-sequential)
            # indices; the original proposal may already contain useful project
            # ideas that should be preserved.
            issues.append(f"Normalized non-sequential phase index {phase_index}")
        phase_metadata.setdefault(phase_index, phase)
        entries = phase.get("skills", [])
        if not isinstance(entries, list):
            issues.append(f"Ignored malformed skills list in phase {phase_index}")
            repaired = True
            continue
        if not entries:
            issues.append(f"Removed empty phase {phase_index}")
            repaired = True
            continue
        for entry in entries:
            if isinstance(entry, dict):
                raw_id = str(entry.get("id") or "").strip()
                raw_name = str(entry.get("name") or "").strip()
            elif isinstance(entry, str):
                raw_id, raw_name = entry.strip(), entry.strip()
            else:
                issues.append(f"Ignored malformed skill entry in phase {phase_index}")
                repaired = True
                continue

            sid = raw_id if raw_id in graph.nodes else name_to_id.get(_key(raw_name or raw_id))
            if not sid:
                issues.append(f"Removed unknown skill: {raw_name or raw_id or '<empty>'}")
                repaired = True
                continue
            if sid not in allowed_ids:
                issues.append(f"Removed out-of-scope skill: {graph.nodes[sid].name or sid}")
                repaired = True
                continue
            if sid in first_phase_by_skill:
                issues.append(f"Removed duplicate skill: {graph.nodes[sid].name or sid}")
                repaired = True
                continue
            first_phase_by_skill[sid] = phase_index
            observed_order.append(sid)

    observed_set = set(observed_order)
    mastered_proposed = {
        sid for sid in observed_set
        if _mastery_value(mastery, sid) >= strong_threshold
    }
    if mastered_proposed:
        issues.append("Removed skills already above the mastery threshold")
        repaired = True

    filtered_order = [sid for sid in observed_order if sid in required_ids]
    filtered_set = set(filtered_order)
    missing_required = required_ids - filtered_set
    if missing_required:
        issues.append(
            "Inserted missing required skills: " + ", ".join(
                graph.nodes[sid].name or sid
                for sid in sorted(missing_required)
            )
        )
        repaired = True

    # Test the model's actual flattened order against every edge whose endpoints
    # are both required. The graph's transitive closure handles paths through
    # mastered skills that are intentionally omitted from the learning path.
    order_position = {sid: pos for pos, sid in enumerate(filtered_order)}
    phase_position = {
        sid: first_phase_by_skill[sid]
        for sid in filtered_order if sid in first_phase_by_skill
    }
    ordering_invalid = False
    for dependent in required_ids:
        for prerequisite in graph.ancestors(dependent) & required_ids:
            if prerequisite not in order_position or dependent not in order_position:
                continue
            if order_position[prerequisite] >= order_position[dependent]:
                ordering_invalid = True
            if (
                prerequisite in phase_position
                and dependent in phase_position
                and phase_position[prerequisite] > phase_position[dependent]
            ):
                ordering_invalid = True
    if ordering_invalid:
        issues.append("Reordered skills to satisfy prerequisite dependencies")
        repaired = True

    if repaired:
        rank = {sid: pos for pos, sid in enumerate(filtered_order)}

        def stable_key(sid: str):
            # Proposed skills retain priority among nodes whose dependencies are
            # already satisfied; inserted skills use deterministic metadata.
            if sid in rank:
                return (0, rank[sid], sid)
            node = graph.nodes[sid]
            return (1, getattr(node, "difficulty", 1), sid)

        ordered_ids = graph.topological_order(required_ids, key=stable_key)

        # Prefer the proposed phase of a skill. A missing prerequisite is placed
        # with the earliest proposed descendant that needs it; dependencies may
        # push later skills into later phases when the proposal grouped them
        # incorrectly.
        desired_phase: Dict[str, int] = {}
        for sid in required_ids:
            if sid in first_phase_by_skill:
                desired_phase[sid] = first_phase_by_skill[sid]
            else:
                descendants = [
                    other for other in first_phase_by_skill
                    if other in required_ids and graph.is_ancestor(sid, other)
                ]
                desired_phase[sid] = min(
                    (first_phase_by_skill[other] for other in descendants),
                    default=max(phase_metadata.keys(), default=-1) + 1,
                )

        assigned_phase: Dict[str, int] = {}
        for sid in ordered_ids:
            prerequisite_phases = [
                assigned_phase[p]
                for p in graph.direct_prereqs(sid)
                if p in required_ids and p in assigned_phase
            ]
            assigned_phase[sid] = max(
                [desired_phase.get(sid, 0), *prerequisite_phases]
            )

        grouped: Dict[int, list] = {}
        for sid in ordered_ids:
            grouped.setdefault(assigned_phase[sid], []).append(sid)
        sorted_groups = sorted(grouped.items())
        # Compress gaps created by empty/removed phases.
        plan_phases = []
        for new_index, (old_index, skill_ids) in enumerate(sorted_groups):
            metadata = phase_metadata.get(old_index, {})
            skill_items = []
            for sid in skill_ids:
                m = _mastery_value(mastery, sid)
                action = "learn" if m < weak_threshold else "review"
                skill_items.append({
                    "id": sid,
                    "name": graph.nodes[sid].name or sid,
                    "action": action,
                })
            title = str(metadata.get("title") or f"Phase {new_index + 1}").strip()
            plan_phases.append({"index": new_index, "title": title, "skills": skill_items})
    else:
        # The proposal is already valid; preserve its authored phase boundaries
        # and titles while normalizing IDs, names, actions and indexes.
        plan_phases = []
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            entries = phase.get("skills", [])
            if not isinstance(entries, list):
                continue
            skills_out = []
            for entry in entries:
                raw_id = str(entry.get("id") or "").strip() if isinstance(entry, dict) else str(entry).strip()
                raw_name = str(entry.get("name") or "").strip() if isinstance(entry, dict) else str(entry).strip()
                sid = raw_id if raw_id in graph.nodes else name_to_id.get(_key(raw_name or raw_id))
                if sid not in required_ids:
                    continue
                m = _mastery_value(mastery, sid)
                skills_out.append({
                    "id": sid,
                    "name": graph.nodes[sid].name or sid,
                    "action": "learn" if m < weak_threshold else "review",
                })
            if skills_out:
                index = len(plan_phases)
                plan_phases.append({
                    "index": index,
                    "title": str(phase.get("title") or f"Phase {index + 1}").strip(),
                    "skills": skills_out,
                })

    if not plan_phases:
        raise GraphError("The validated roadmap has no skills to teach")

    # A final invariant check avoids depending solely on the repair algorithm.
    flattened = [sk["id"] for phase in plan_phases for sk in phase["skills"]]
    positions = {sid: idx for idx, sid in enumerate(flattened)}
    for dependent in required_ids:
        for prerequisite in graph.ancestors(dependent) & required_ids:
            if prerequisite not in positions or dependent not in positions:
                raise GraphError("Validated roadmap omitted a required prerequisite")
            if positions[prerequisite] >= positions[dependent]:
                raise GraphError("Validated roadmap still violates prerequisite ordering")

    return {"plan_phases": plan_phases, "repaired": repaired, "issues": issues}
