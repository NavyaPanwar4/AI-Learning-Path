import json
import uuid

from app.db.database import SessionLocal
from app.db.models import Goal, Roadmap, Skill, UserSkill
from app.services.activity_service import activity_service
from app.services.auth_service import auth_service
from app.services.gap_analysis import gap_analysis_service
from app.services.link_validator import filter_valid_resources
from app.services.llm_service import llm_service
from app.services.web_search_service import web_search_service


class RoadmapService:

    # ------------------------------------------------------------------
    # Study-notes normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_study_notes(notes):
        """
        Normalize study notes returned by the LLM.

        Qwen3 can occasionally generate malformed key_concepts such as:

            {
                "MERCHANTABILITY": "Middleware",
                "explanation": "..."
            }

        instead of:

            {
                "term": "Middleware",
                "explanation": "..."
            }

        This method repairs those objects before FastAPI/Pydantic
        validates the roadmap response.
        """

        if not isinstance(notes, dict):
            return notes

        key_concepts = notes.get("key_concepts", [])

        if not isinstance(key_concepts, list):
            notes["key_concepts"] = []
            return notes

        normalized_concepts = []

        for concept in key_concepts:

            if not isinstance(concept, dict):
                continue

            # Already valid.
            if (
                concept.get("term")
                and concept.get("explanation")
            ):
                normalized_concepts.append(
                    {
                        "term": str(concept["term"]),
                        "explanation": str(
                            concept["explanation"]
                        ),
                    }
                )
                continue

            # Recover malformed objects where Qwen3 used the
            # concept name as the key.
            explanation = concept.get(
                "explanation",
                "",
            )

            concept_name = next(
                (
                    key
                    for key in concept.keys()
                    if key != "explanation"
                ),
                None,
            )

            if concept_name and explanation:
                concept_value = concept.get(
                    concept_name
                )

                if concept_value:
                    normalized_concepts.append(
                        {
                            "term": str(
                                concept_value
                            ),
                            "explanation": str(
                                explanation
                            ),
                        }
                    )

        notes["key_concepts"] = normalized_concepts

        return notes

    @classmethod
    def _normalize_roadmap(cls, roadmap):
        """
        Normalize roadmap data before it is returned through FastAPI.

        This also repairs malformed study notes that were generated
        and saved before the LLM normalization fix was added.
        """

        if not isinstance(roadmap, dict):
            return roadmap

        phases = roadmap.get("phases", [])

        if not isinstance(phases, list):
            return roadmap

        changed = False

        for phase in phases:

            if not isinstance(phase, dict):
                continue

            ai_notes = phase.get("ai_notes")

            if isinstance(ai_notes, dict):
                original = json.dumps(
                    ai_notes,
                    sort_keys=True,
                    ensure_ascii=False,
                )

                normalized = cls._normalize_study_notes(
                    ai_notes
                )

                updated = json.dumps(
                    normalized,
                    sort_keys=True,
                    ensure_ascii=False,
                )

                if original != updated:
                    changed = True

                phase["ai_notes"] = normalized

        return roadmap

    # ------------------------------------------------------------------
    # Roadmap generation
    # ------------------------------------------------------------------

    def generate_personalized_roadmap(self, user_id: str):

        # 1. Load user profile
        user_profile = auth_service.get_user_by_id(user_id)

        if not user_profile:
            raise ValueError("User not found")

        goal_id = str(
            user_profile.get("goal_id")
            or "default"
        )

        db = SessionLocal()

        try:
            goal = (
                db.query(Goal)
                .filter(
                    Goal.goal_id == goal_id
                )
                .first()
            )

            goal_name = (
                goal.goal_name
                if goal
                else "Unknown Goal"
            )

            # 2. Identify missing + possessed skills
            missing_skills = (
                gap_analysis_service.identify_missing_skills(
                    user_id
                )
            )

            possessed_skill_ids = [
                us.skill_id
                for us in (
                    db.query(UserSkill)
                    .filter(
                        UserSkill.user_id
                        == str(user_id)
                    )
                    .all()
                )
            ]

            possessed_skills = []

            for sid in possessed_skill_ids:

                skill = (
                    db.query(Skill)
                    .filter(
                        Skill.skill_id
                        == str(sid)
                    )
                    .first()
                )

                if skill:
                    possessed_skills.append(
                        skill.skill_name
                    )

        finally:
            db.close()

        # 3. Retrieve RAG context
        try:
            verified_live_resources = (
                web_search_service.search_courses(
                    missing_skills
                )
            )

        except Exception as exc:
            from app.utils.logger import logger

            logger.error(
                f"Live web search failed, "
                f"continuing without it: {exc}"
            )

            verified_live_resources = []

        # 4. Construct context for LLM
        context = {
            "experience_level": user_profile.get(
                "experience_level"
            ),
            "available_hours_per_week": user_profile.get(
                "available_hours_per_week"
            ),
            "learning_style": user_profile.get(
                "learning_style"
            ),
            "missing_skills": missing_skills,
            "possessed_skills": possessed_skills,
            "verified_live_resources": (
                verified_live_resources
            ),
            "goal_skill_name": goal_name,
        }

        # 5. Generate roadmap via local LLM
        roadmap_dict = (
            llm_service.generate_roadmap(
                context
            )
        )

        # The frontend needs the goal ID immediately
        # after generating a new roadmap.
        if isinstance(roadmap_dict, dict):
            roadmap_dict["goal_id"] = goal_id

        # 5.5 Belt-and-suspenders:
        # re-validate every resource link the LLM output.
        if isinstance(roadmap_dict, dict):

            for phase in roadmap_dict.get(
                "phases",
                [],
            ):

                if phase.get("resources"):
                    phase["resources"] = (
                        filter_valid_resources(
                            phase["resources"]
                        )
                    )

        # 5.6 Normalize any study notes that may already
        # exist in generated data.
        roadmap_dict = self._normalize_roadmap(
            roadmap_dict
        )

        # 6. Upsert into DB
        if roadmap_dict and (
            roadmap_dict.get("phases")
            or roadmap_dict.get("roadmap_text")
        ):

            db = SessionLocal()

            try:
                existing = (
                    db.query(Roadmap)
                    .filter(
                        Roadmap.user_id
                        == str(user_id),
                        Roadmap.goal_id
                        == goal_id,
                    )
                    .first()
                )

                if existing:
                    existing.data = json.dumps(
                        roadmap_dict
                    )
                    existing.goal_name = goal_name
                    existing.is_complete = False

                else:
                    db.add(
                        Roadmap(
                            user_id=str(user_id),
                            goal_id=goal_id,
                            goal_name=goal_name,
                            data=json.dumps(
                                roadmap_dict
                            ),
                            is_complete=False,
                        )
                    )

                db.commit()

            except Exception:
                db.rollback()

            finally:
                db.close()

        activity_service.log_activity(
            user_id,
            "roadmap_generated",
        )

        return roadmap_dict

    # ------------------------------------------------------------------
    # Saved roadmaps
    # ------------------------------------------------------------------

    def get_saved_roadmaps(
        self,
        user_id: str,
    ):

        db = SessionLocal()

        try:
            rows = (
                db.query(Roadmap)
                .filter(
                    Roadmap.user_id
                    == str(user_id)
                )
                .all()
            )

            return [
                {
                    "goal_id": r.goal_id,
                    "goal_name": r.goal_name,
                    "is_complete": r.is_complete,
                }
                for r in rows
            ]

        finally:
            db.close()

    def get_saved_roadmap(
        self,
        user_id: str,
        goal_id: str,
    ):

        db = SessionLocal()

        try:
            row = (
                db.query(Roadmap)
                .filter(
                    Roadmap.user_id
                    == str(user_id),
                    Roadmap.goal_id
                    == str(goal_id),
                )
                .first()
            )

            if not row:
                return None

            roadmap = json.loads(row.data)

            roadmap["goal_id"] = row.goal_id

            # Repair malformed study notes already stored
            # in the database.
            original_data = json.dumps(
                roadmap,
                sort_keys=True,
                ensure_ascii=False,
            )

            roadmap = self._normalize_roadmap(
                roadmap
            )

            normalized_data = json.dumps(
                roadmap,
                sort_keys=True,
                ensure_ascii=False,
            )

            # Persist the repaired roadmap so this problem
            # does not occur again for this saved roadmap.
            if original_data != normalized_data:
                row.data = json.dumps(
                    roadmap,
                    ensure_ascii=False,
                )
                db.commit()

            return roadmap

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Delete roadmap
    # ------------------------------------------------------------------

    def delete_roadmap(
        self,
        user_id: str,
        goal_id: str,
    ) -> bool:

        db = SessionLocal()

        try:
            row = (
                db.query(Roadmap)
                .filter(
                    Roadmap.user_id
                    == str(user_id),
                    Roadmap.goal_id
                    == str(goal_id),
                )
                .first()
            )

            if not row:
                return False

            db.delete(row)
            db.commit()

            return True

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Phase status
    # ------------------------------------------------------------------

    def update_phase_status(
        self,
        user_id: str,
        goal_id: str,
        phase_index: int,
        completed: bool,
    ):

        db = SessionLocal()

        try:
            row = (
                db.query(Roadmap)
                .filter(
                    Roadmap.user_id
                    == str(user_id),
                    Roadmap.goal_id
                    == str(goal_id),
                )
                .first()
            )

            if not row:
                return None

            roadmap = json.loads(row.data)

            phases = roadmap.get(
                "phases",
                [],
            )

            if 0 <= phase_index < len(phases):
                phases[phase_index][
                    "completed"
                ] = completed

            row.data = json.dumps(
                roadmap
            )

            db.commit()

            return roadmap

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Study notes
    # ------------------------------------------------------------------

    def generate_phase_study_notes(
        self,
        user_id: str,
        goal_id: str,
        phase_index: int,
    ):
        """
        Generate and persist notes so learners do not pay
        for the same phase twice.
        """

        db = SessionLocal()

        try:
            row = (
                db.query(Roadmap)
                .filter(
                    Roadmap.user_id
                    == str(user_id),
                    Roadmap.goal_id
                    == str(goal_id),
                )
                .first()
            )

            if not row:
                return None

            roadmap = json.loads(row.data)

            phases = roadmap.get(
                "phases",
                [],
            )

            if not 0 <= phase_index < len(phases):
                return None

            phase = phases[phase_index]

            # If notes already exist, normalize them before
            # returning them. This also repairs notes that were
            # generated before the fix.
            if phase.get("ai_notes"):

                normalized_notes = (
                    self._normalize_study_notes(
                        phase["ai_notes"]
                    )
                )

                phase["ai_notes"] = normalized_notes

                row.data = json.dumps(
                    roadmap,
                    ensure_ascii=False,
                )

                db.commit()

                return normalized_notes

            profile = (
                auth_service.get_user_by_id(
                    user_id
                )
                or {}
            )

            notes = (
                llm_service.generate_study_notes(
                    phase_title=phase.get(
                        "title",
                        f"Phase {phase_index + 1}",
                    ),
                    skills=phase.get(
                        "skills",
                        [],
                    ),
                    duration=phase.get(
                        "duration",
                        "At your own pace",
                    ),
                    experience_level=profile.get(
                        "experience_level",
                        "beginner",
                    ),
                )
            )

            # Normalize the newly generated notes
            # before saving them.
            notes = self._normalize_study_notes(
                notes
            )

            required_fields = {
                "title",
                "overview",
            }

            if not notes or not required_fields.issubset(
                notes
            ):
                raise ValueError(
                    "The local AI model could not "
                    "generate study notes. "
                    "Please try again."
                )

            phase["ai_notes"] = notes

            row.data = json.dumps(
                roadmap,
                ensure_ascii=False,
            )

            db.commit()

            return notes

        finally:
            db.close()

    # ------------------------------------------------------------------
    # Complete roadmap
    # ------------------------------------------------------------------

    def complete_roadmap(
        self,
        user_id: str,
        goal_id: str,
    ):

        db = SessionLocal()

        try:
            row = (
                db.query(Roadmap)
                .filter(
                    Roadmap.user_id
                    == str(user_id),
                    Roadmap.goal_id
                    == str(goal_id),
                )
                .first()
            )

            if not row:
                return None

            roadmap = json.loads(row.data)

            roadmap["is_complete"] = True

            row.data = json.dumps(
                roadmap
            )

            row.is_complete = True

            db.commit()

            # Add learned skills
            try:
                learned_skills = set()

                for phase in roadmap.get(
                    "phases",
                    [],
                ):

                    for skill in phase.get(
                        "skills",
                        [],
                    ):
                        learned_skills.add(
                            skill
                        )

                for skill_name in learned_skills:

                    skill = (
                        db.query(Skill)
                        .filter(
                            Skill.skill_name.ilike(
                                str(skill_name)
                            )
                        )
                        .first()
                    )

                    if skill:
                        skill_id = skill.skill_id

                    else:
                        skill_id = str(
                            uuid.uuid4()
                        )

                        db.add(
                            Skill(
                                skill_id=skill_id,
                                skill_name=str(
                                    skill_name
                                ),
                                category=(
                                    "Learned from Roadmap"
                                ),
                            )
                        )

                        db.commit()

                    exists = (
                        db.query(UserSkill)
                        .filter(
                            UserSkill.user_id
                            == str(user_id),
                            UserSkill.skill_id
                            == skill_id,
                        )
                        .first()
                    )

                    if not exists:
                        db.add(
                            UserSkill(
                                user_id=str(
                                    user_id
                                ),
                                skill_id=skill_id,
                                proficiency=1,
                            )
                        )

                db.commit()

            except Exception as e:
                from app.utils.logger import logger

                logger.error(
                    "Error adding learned skills "
                    f"on roadmap completion: {e}"
                )

                db.rollback()

            activity_service.log_activity(
                user_id,
                "roadmap_completed",
            )

            return roadmap

        finally:
            db.close()


roadmap_service = RoadmapService()