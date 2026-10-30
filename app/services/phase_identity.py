"""Stable identity and conservative matching for roadmap phases."""
from __future__ import annotations
import re
import uuid

def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()

def _skills(phase: dict) -> set[str]:
    values = phase.get("skills", []) or []
    if isinstance(values, str): values = [values]
    return {_norm(value) for value in values if _norm(value)}

def ensure_phase_ids(roadmap: dict) -> bool:
    """Assign stable IDs to phases without IDs; return whether anything changed."""
    changed = False
    if not isinstance(roadmap, dict): return changed
    for phase in roadmap.get("phases", []) or []:
        if isinstance(phase, dict) and not phase.get("phase_id"):
            phase["phase_id"] = str(uuid.uuid4())
            changed = True
    return changed

def _compatibility(old: dict, new: dict) -> tuple[bool, float]:
    old_title, new_title = _norm(old.get("title")), _norm(new.get("title"))
    old_skills, new_skills = _skills(old), _skills(new)
    if old_skills and new_skills:
        intersection = len(old_skills & new_skills)
        union = len(old_skills | new_skills)
        jaccard = intersection / union if union else 0.0
        same_skills = old_skills == new_skills
        # A matching title alone is not enough to preserve a phase's state.
        compatible = same_skills or (old_title == new_title and jaccard >= 0.5) or jaccard >= 0.8
        return compatible, (10.0 if same_skills else 0.0) + 4.0 * jaccard + (2.0 if old_title and old_title == new_title else 0.0)
    if not old_skills and not new_skills and old_title and old_title == new_title:
        return True, 2.0
    return False, 0.0

def preserve_phase_identity(previous: dict, generated: dict) -> dict:
    """Preserve state only for one-to-one matches grounded in title and skill content."""
    ensure_phase_ids(previous)
    ensure_phase_ids(generated)
    old_phases = [p for p in (previous.get("phases", []) or []) if isinstance(p, dict)]
    new_phases = [p for p in (generated.get("phases", []) or []) if isinstance(p, dict)]
    candidates = []
    for oi, old in enumerate(old_phases):
        for ni, new in enumerate(new_phases):
            compatible, score = _compatibility(old, new)
            if compatible: candidates.append((score, oi, ni))
    candidates.sort(reverse=True)
    used_old, used_new = set(), set()
    for _, oi, ni in candidates:
        if oi in used_old or ni in used_new: continue
        old, new = old_phases[oi], new_phases[ni]
        new["phase_id"] = old["phase_id"]
        new["completed"] = bool(old.get("completed"))
        if old.get("ai_notes"): new["ai_notes"] = old["ai_notes"]
        used_old.add(oi); used_new.add(ni)
    generated["is_complete"] = bool(previous.get("is_complete")) and all(bool(p.get("completed")) for p in new_phases)
    return generated

def backfill_attempt_phase_ids(attempts, phases: list[dict]) -> None:
    """Associate legacy index-only attempts with the phase list they currently reference."""
    for attempt in attempts:
        if not getattr(attempt, "phase_id", None) and 0 <= attempt.phase_index < len(phases):
            attempt.phase_id = phases[attempt.phase_index].get("phase_id")

def shift_attempt_indices_after_insertion(attempts, inserted_after_index: int) -> None:
    """Keep ordinal indices aligned after inserting one phase after an index."""
    for attempt in attempts:
        if attempt.phase_index > inserted_after_index:
            attempt.phase_index += 1

def reconcile_attempts_to_phase_order(attempts, previous_phases: list[dict], generated_phases: list[dict]) -> None:
    """Backfill legacy IDs, then refresh numeric indices from stable phase IDs."""
    backfill_attempt_phase_ids(attempts, previous_phases)
    new_index_by_id = {phase.get("phase_id"): index for index, phase in enumerate(generated_phases) if phase.get("phase_id")}
    for attempt in attempts:
        if attempt.phase_id in new_index_by_id:
            attempt.phase_index = new_index_by_id[attempt.phase_id]
