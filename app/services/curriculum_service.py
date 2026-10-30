"""Curated, goal-specific curricula used as the source of truth for roadmaps.

The database's legacy skill-dependency graph contains cross-domain and
incorrect edges. This service deliberately does not traverse that graph. Each
known goal uses its reviewed curriculum, and the LLM only elaborates the fixed
phase plan rather than choosing which skills belong in it.
"""

import json
import os
from typing import Mapping, Optional, Iterable

from app.utils.config import settings


class CurriculumService:
    def __init__(self, curriculum_path: Optional[str] = None):
        self.curriculum_path = curriculum_path or os.path.join(
            settings.DATASET_DIR, "goal_curricula.json"
        )
        self._curricula = None

    def _load(self) -> dict:
        if self._curricula is None:
            with open(self.curriculum_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise ValueError("goal_curricula.json must contain a JSON object")
            self._curricula = loaded
        return self._curricula

    def has_curriculum(self, goal_id: str) -> bool:
        return str(goal_id) in self._load()

    def get_skill_ids(self, goal_id: str) -> Optional[list[str]]:
        """Return every skill ID in a curated goal, in curriculum order.

        Unlike ``build_plan``, this method does not remove skills the learner
        has recorded as known. The full scope is needed by LLM-first planning
        so goal-scoped mastery evidence can override global ``UserSkill`` state.
        """
        curriculum = self._load().get(str(goal_id))
        if curriculum is None:
            return None
        return list(dict.fromkeys(
            str(skill_id)
            for phase in curriculum.get("phases", [])
            for skill_id in phase.get("skill_ids", [])
        ))

    def build_plan(
        self,
        goal_id: str,
        skills_by_id: Mapping[str, object],
        possessed_skill_ids: Iterable[str] = (),
    ) -> Optional[list]:
        """Build fixed phase dictionaries, or None for an uncurated goal.

        ``skills_by_id`` maps IDs to ORM Skill objects. A skill already present
        in the learner's UserSkill records is omitted, preserving the app's
        existing behavior of not re-teaching recorded skills.
        """
        curriculum = self._load().get(str(goal_id))
        if curriculum is None:
            return None

        possessed = {str(skill_id) for skill_id in possessed_skill_ids}
        plan = []
        index = 0
        for phase in curriculum.get("phases", []):
            items = []
            for raw_id in phase.get("skill_ids", []):
                skill_id = str(raw_id)
                skill = skills_by_id.get(skill_id)
                if skill is None or skill_id in possessed:
                    continue
                name = getattr(skill, "skill_name", None)
                if not name:
                    continue
                items.append({"id": skill_id, "name": str(name), "action": "learn"})
            # Drop empty phases after learner-specific skills are removed.
            if not items:
                continue
            plan.append({
                "index": index,
                "title": str(phase.get("title") or f"Phase {index + 1}"),
                "skills": items,
            })
            index += 1
        return plan


curriculum_service = CurriculumService()
