"""Goal-aware skill gap analysis and deterministic fallback planning.

Reviewed goal curricula define the intended skill scope for curated goals and
remain the safe fallback if LLM-first generation fails. Uncurated goals derive
required skills from goal-skill mappings plus prerequisite closure. The main
roadmap path may let the LLM propose phase grouping, while deterministic
validation enforces scope, mastery and prerequisite constraints.
"""

import heapq

from app.db.database import SessionLocal
from app.db.models import GoalSkill, Skill, SkillDependency, User, UserSkill
from app.services.curriculum_service import curriculum_service
from app.utils.logger import logger


class GapAnalysisService:
    def get_curated_plan(self, user_id: str):
        """Return a fixed curriculum plan for a seeded goal, or ``None``."""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == str(user_id)).first()
            if not user or not user.goal_id:
                return None

            skills_by_id = {
                str(skill.skill_id): skill for skill in db.query(Skill).all()
            }
            current_skill_ids = {
                str(us.skill_id)
                for us in db.query(UserSkill)
                .filter(UserSkill.user_id == str(user_id))
                .all()
            }
            return curriculum_service.build_plan(
                str(user.goal_id), skills_by_id, current_skill_ids
            )
        finally:
            db.close()

    def _get_ordered_missing_skill_records(self, user_id: str) -> list[dict]:
        """Return goal skills plus prerequisites in prerequisite-first order.

        Used only for goals without a curated curriculum. The previous
        implementation expanded a set and returned it directly, which made
        skill order nondeterministic and exposed LLM generation to a noisy
        prerequisite graph.
        """
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == str(user_id)).first()
            if not user or not user.goal_id:
                return []

            skill_by_id = {
                str(skill.skill_id): skill for skill in db.query(Skill).all()
            }
            possessed = {
                str(us.skill_id)
                for us in db.query(UserSkill)
                .filter(UserSkill.user_id == str(user_id))
                .all()
            }

            target_links = (
                db.query(GoalSkill)
                .filter(GoalSkill.goal_id == str(user.goal_id))
                .all()
            )
            target_links = sorted(
                target_links,
                key=lambda link: (
                    -int(link.importance or 0),
                    skill_by_id.get(str(link.skill_id)).skill_name.casefold()
                    if skill_by_id.get(str(link.skill_id))
                    else str(link.skill_id),
                    str(link.skill_id),
                ),
            )
            target_ids = [
                str(link.skill_id)
                for link in target_links
                if str(link.skill_id) in skill_by_id
                and str(link.skill_id) not in possessed
            ]
            if not target_ids:
                return []

            # Edges are represented as dependent skill -> prerequisites.
            prereq_map: dict[str, set[str]] = {}
            for edge in db.query(SkillDependency).all():
                dependent = str(edge.skill_id)
                prerequisite = str(edge.prerequisite_id)
                if dependent in skill_by_id and prerequisite in skill_by_id:
                    prereq_map.setdefault(dependent, set()).add(prerequisite)

            required = set(target_ids)
            stack = list(target_ids)
            while stack:
                dependent = stack.pop()
                for prerequisite in prereq_map.get(dependent, set()):
                    if prerequisite not in possessed and prerequisite not in required:
                        required.add(prerequisite)
                        stack.append(prerequisite)

            target_rank = {skill_id: index for index, skill_id in enumerate(target_ids)}
            indegree = {skill_id: 0 for skill_id in required}
            dependents: dict[str, set[str]] = {skill_id: set() for skill_id in required}
            for dependent in required:
                for prerequisite in prereq_map.get(dependent, set()):
                    if prerequisite in required:
                        indegree[dependent] += 1
                        dependents[prerequisite].add(dependent)

            def sort_key(skill_id: str):
                skill = skill_by_id[skill_id]
                return (
                    target_rank.get(skill_id, len(target_rank) + 1),
                    str(skill.skill_name).casefold(),
                    skill_id,
                )

            ready = [(sort_key(skill_id), skill_id)
                     for skill_id, degree in indegree.items() if degree == 0]
            heapq.heapify(ready)
            ordered_ids = []
            while ready:
                _, skill_id = heapq.heappop(ready)
                ordered_ids.append(skill_id)
                for dependent in dependents[skill_id]:
                    indegree[dependent] -= 1
                    if indegree[dependent] == 0:
                        heapq.heappush(ready, (sort_key(dependent), dependent))

            # Defensive handling for a cycle in a user's locally modified DB.
            # The catalog sync script repairs the shipped graph; this prevents
            # one custom graph cycle from crashing roadmap generation.
            if len(ordered_ids) != len(required):
                leftovers = sorted(required - set(ordered_ids), key=sort_key)
                logger.warning(
                    "Prerequisite graph cycle detected for user %s; placing %d "
                    "remaining skills deterministically at the end.",
                    user_id,
                    len(leftovers),
                )
                ordered_ids.extend(leftovers)

            return [
                {
                    "id": skill_id,
                    "name": str(skill_by_id[skill_id].skill_name),
                    "action": "learn",
                }
                for skill_id in ordered_ids
            ]
        finally:
            db.close()

    def get_fallback_plan(self, user_id: str, skills_per_phase: int = 3):
        """Build a deterministic plan for a goal without a curated curriculum.

        The LLM may name phases and add teaching details, but membership and
        prerequisite ordering are fixed before the provider is called.
        """
        items = self._get_ordered_missing_skill_records(user_id)
        if not items:
            return None

        chunk_size = max(1, int(skills_per_phase))
        phases = []
        for offset in range(0, len(items), chunk_size):
            phase_items = items[offset:offset + chunk_size]
            phase_names = [item["name"] for item in phase_items]
            # The deterministic title avoids an LLM-generated unrelated title
            # on fallback/custom-goal paths.
            phases.append({
                "index": len(phases),
                "title": f"Phase {len(phases) + 1}: {', '.join(phase_names[:2])}",
                "skills": phase_items,
            })
        return phases

    def identify_missing_skills(self, user_id: str) -> list:
        """Return required skills in deterministic curriculum order."""
        curated_plan = self.get_curated_plan(user_id)
        if curated_plan is not None:
            return [
                skill["name"]
                for phase in curated_plan
                for skill in phase["skills"]
            ]
        return [
            item["name"] for item in (self._get_ordered_missing_skill_records(user_id) or [])
        ]


gap_analysis_service = GapAnalysisService()
