"""Experimental conditions A-E: prompt construction, output parsing, planner use.

Information ladder (what each condition is given)
  A  LLM-only      goal targets, full mastery table, skill catalogue, general
                   personalisation instructions (mirrors the production prompt:
                   "progress foundational -> advanced", "don't re-teach known skills").
  E  A + structure A plus the direct-prerequisite edges and the explicit rule text
                   (mastery thresholds, include unmastered prerequisites, order).
                   Information equals what the planner uses; nothing is enforced.
  D  proposed      path_planner decides skills/order/actions (enforced);
                   the LLM only elaborates (titles/durations).
  B  planner, graph only (no mastery)         -- deterministic, no LLM
  C  A's skill list filtered by mastery rules -- derived from A's output, no graph
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional, Sequence

from app.services.llm_service import LLMService
from app.services.path_planner import PlannerConfig, SkillGraph, plan_path

SCHEMA = '''{
  "phases": [
    {"title": "short phase title",
     "skills": [{"id": "<catalogue id>", "action": "learn"}]}
  ]
}'''


def catalogue_text(graph: SkillGraph) -> str:
    return "\n".join(f'{n.skill_id} | {n.name} | difficulty {n.difficulty} | {n.hours:g} h'
                     for n in graph.nodes.values())


def mastery_text(graph: SkillGraph, mastery: Dict[str, float]) -> str:
    return "\n".join(f'{sid} | {graph.nodes[sid].name} | {round(100 * mastery.get(sid, 0.0))}%'
                     for sid in graph.nodes)


def targets_text(graph: SkillGraph, targets: Sequence[str]) -> str:
    return "\n".join(f'{t} | {graph.nodes[t].name}' for t in targets)


def edges_text(graph: SkillGraph) -> str:
    return "\n".join(f'{graph.nodes[v].name} ({v}) requires {graph.nodes[u].name} ({u})'
                     for u, v in graph.edges())


def _base(goal_name, graph, targets, mastery) -> str:
    return f"""You are designing a personalised learning path.

GOAL: {goal_name}

TARGET SKILLS (the learner must be able to do all of these at the end):
{targets_text(graph, targets)}

SKILL CATALOGUE (id | name | difficulty | estimated hours):
{catalogue_text(graph)}

LEARNER'S CURRENT MASTERY (0-100% per catalogue skill):
{mastery_text(graph, mastery)}
"""


PROMPT_VARIANTS = ("v1", "v2", "v3")   # v1 = the prompts used in the main experiments; v2/v3 = paraphrases


def _base_v2(goal_name, graph, targets, mastery) -> str:
    return f"""Please plan a learning path for one learner.

Career goal: {goal_name}

The learner has to be able to do each of these target skills at the end:
{targets_text(graph, targets)}

All available skills (id | name | difficulty | estimated hours):
{catalogue_text(graph)}

What the learner currently knows (percent mastery for every skill):
{mastery_text(graph, mastery)}
"""


def prompt_a(goal_name, graph, targets, mastery, max_phases=7, variant="v1") -> str:
    if variant == "v2":
        return _base_v2(goal_name, graph, targets, mastery) + f"""
Task:
- Pick the skills that belong in this learner's path, put them in a sensible teaching order, and split them into no more than {max_phases} phases.
- Tailor the path to what this learner already knows; avoid spending time on skills they have already mastered.
- Start with foundations and move toward advanced material.
- Only use ids from the skill list, and use each skill at most once.
- Mark each skill "learn" (teach it fully) or "review" (brief refresher).

Reply with JSON only, in this shape:
{SCHEMA}
"""
    if variant == "v3":
        return f"""TASK: personalised learning path (at most {max_phases} phases; ids from the catalogue only, each at most once; action is "learn" or "review").
Goal: {goal_name}. Tailor to the learner's existing mastery (do not re-teach known skills) and go from foundational to advanced.

Learner's current mastery (0-100%):
{mastery_text(graph, mastery)}

Target skills:
{targets_text(graph, targets)}

Catalogue (id | name | difficulty | hours):
{catalogue_text(graph)}

Output ONLY JSON of this form:
{SCHEMA}
"""
    return _base(goal_name, graph, targets, mastery) + f"""
INSTRUCTIONS:
- Choose which catalogue skills to include, order them, and group them into at most {max_phases} phases.
- Personalise the path to this learner's mastery: do not spend time re-teaching skills the learner already knows.
- Progress from foundational to advanced skills.
- Use ONLY skill ids from the catalogue. Each skill may appear at most once.
- "action" is "learn" (full instruction) or "review" (short refresher).

Return ONLY valid JSON of this form:
{SCHEMA}
"""


def prompt_e(goal_name, graph, targets, mastery, weak, strong, max_phases=7, variant="v1") -> str:
    if variant == "v2":
        return _base_v2(goal_name, graph, targets, mastery) + f"""
Direct prerequisites between skills:
{edges_text(graph)}

Follow these rules exactly:
1. Treat a skill as mastered when mastery is at least {round(100 * strong)}%; never include mastered skills.
2. Include every target that is not mastered, plus every not-mastered prerequisite (direct or indirect) of any skill you include.
3. Mark a skill "learn" when mastery is below {round(100 * weak)}%, otherwise "review".
4. Each skill must come after all of its included prerequisites.
5. Split the ordered skills into no more than {max_phases} phases, using only catalogue ids, each at most once.

Reply with JSON only, in this shape:
{SCHEMA}
"""
    if variant == "v3":
        return f"""TASK: personalised learning path. Apply the rules exactly.
Goal: {goal_name}

RULES
- Mastered = mastery >= {round(100 * strong)}%. Never include mastered skills.
- Include each unmastered target and every unmastered direct or indirect prerequisite of an included skill.
- Action "learn" if mastery < {round(100 * weak)}%, else "review".
- Every skill comes after all its included prerequisites.
- At most {max_phases} phases; catalogue ids only; each skill at most once.

Prerequisite graph (direct prerequisites):
{edges_text(graph)}

Learner's current mastery (0-100%):
{mastery_text(graph, mastery)}

Target skills:
{targets_text(graph, targets)}

Catalogue (id | name | difficulty | hours):
{catalogue_text(graph)}

Output ONLY JSON of this form:
{SCHEMA}
"""
    return _base(goal_name, graph, targets, mastery) + f"""
PREREQUISITE GRAPH (direct prerequisites):
{edges_text(graph)}

RULES (apply them exactly):
1. A skill is MASTERED if mastery >= {round(100 * strong)}%. Do not include mastered skills.
2. Include every target skill that is not mastered, and every not-mastered prerequisite (direct or indirect) of an included skill.
3. Use action "learn" if mastery < {round(100 * weak)}%, otherwise "review".
4. Place every skill after all of its prerequisites that are included in the path.
5. Group the ordered skills into at most {max_phases} phases. Use ONLY catalogue ids; each skill at most once.

Return ONLY valid JSON of this form:
{SCHEMA}
"""


def prompt_d(plan_phases: list, goal_name: str) -> str:
    return LLMService.build_plan_elaboration_prompt(plan_phases, goal_name=goal_name, include_extras=False)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Parsing LLM output into a neutral path
# ---------------------------------------------------------------------------

def parse_path(parsed: Optional[dict], graph: SkillGraph) -> Optional[List[dict]]:
    """Convert LLM JSON to ``[{"skill_id", "action", "phase"}]``.

    Accepts entries as ``{"id","action"}``, ``{"name"}``, or bare strings
    (id or exact case-insensitive name). Unresolvable entries are kept with
    ``skill_id=None`` so the invalid-item rate can be computed. Returns None if
    the structure has no ``phases`` list at all (a parse failure).
    """
    if not isinstance(parsed, dict) or not isinstance(parsed.get("phases"), list):
        return None
    by_name = {n.name.casefold(): sid for sid, n in graph.nodes.items()}
    items: List[dict] = []
    for pi, phase in enumerate(parsed["phases"]):
        skills = phase.get("skills", []) if isinstance(phase, dict) else []
        if not isinstance(skills, list):
            continue
        for entry in skills:
            action = None
            if isinstance(entry, dict):
                action = entry.get("action")
                key = entry.get("id", entry.get("skill_id", entry.get("name")))
            else:
                key = entry
            key = str(key).strip() if key is not None else ""
            sid = key if key in graph.nodes else by_name.get(key.casefold())
            items.append({"skill_id": sid, "action": action if action in ("learn", "review") else None,
                          "phase": pi})
    return items


# ---------------------------------------------------------------------------
# Planner-derived conditions
# ---------------------------------------------------------------------------

def plan_to_items(plan) -> List[dict]:
    return [{"skill_id": i.skill_id, "action": i.action, "phase": i.phase_index} for i in plan.items]


def planner_plan(graph, targets, mastery, weak, strong, use_graph=True, use_mastery=True,
                 candidates=None, items_per_phase=4):
    cfg = PlannerConfig(weak=weak, strong=strong, use_graph=use_graph, use_mastery=use_mastery,
                        items_per_phase=items_per_phase)
    return plan_path(graph, targets, mastery, cfg, candidates=candidates)


def plan_phases_for_prompt(plan) -> List[dict]:
    return [{"index": idx, "skills": [{"id": it.skill_id, "name": it.name, "action": it.action} for it in ph]}
            for idx, ph in enumerate(plan.phases)]
