import json
import math
import uuid

from app.services.phase_identity import ensure_phase_ids, preserve_phase_identity, reconcile_attempts_to_phase_order

from app.db.database import SessionLocal
from app.db.models import (
    Goal,
    GoalSkill,
    Roadmap,
    RoadmapVersion,
    RoadmapGenerationJob,
    Skill,
    SkillDependency,
    UserSkill,
    GoalUserSkill,
    QuizAttempt,
    QuizQuestionHistory,
)
from app.models.schemas import RoadmapResponse
from app.services.activity_service import activity_service
from app.services.auth_service import auth_service
from app.services.gap_analysis import gap_analysis_service
from app.services.curriculum_service import curriculum_service
from app.services.link_validator import deduplicate_resources_across_phases, filter_relevant_resources
from app.services.llm_service import llm_service
from app.services.web_search_service import web_search_service
from app.services.learning_features_service import learning_features_service
from app.services.mastery_decay import decay_mastery, load_last_reviewed_at_by_skill, normalize_skill_name
from app.services.bkt_parameters import get_bkt_parameters
from app.services.path_planner import PlannerConfig, SkillGraph, SkillNode, plan_path
from app.services.roadmap_validator import validate_llm_roadmap_proposal
from app.utils.config import settings
from app.utils.logger import logger


class RoadmapService:

    def create_generation_job(self, user_id: str) -> dict:
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(RoadmapGenerationJob(job_id=job_id, user_id=str(user_id), status="queued"))
            db.commit()
            return {"job_id": job_id, "status": "queued"}
        finally:
            db.close()

    def run_generation_job(self, job_id: str, user_id: str) -> None:
        db = SessionLocal()
        try:
            job = db.query(RoadmapGenerationJob).filter(RoadmapGenerationJob.job_id == job_id, RoadmapGenerationJob.user_id == str(user_id)).first()
            if not job:
                return
            job.status = "running"
            db.commit()
        finally:
            db.close()
        try:
            roadmap = self.generate_personalized_roadmap(user_id)
            db = SessionLocal()
            try:
                job = db.query(RoadmapGenerationJob).filter(RoadmapGenerationJob.job_id == job_id).first()
                job.status = "completed"
                job.goal_id = roadmap.get("goal_id") if roadmap else None
                db.commit()
            finally:
                db.close()
        except Exception as exc:
            db = SessionLocal()
            try:
                job = db.query(RoadmapGenerationJob).filter(RoadmapGenerationJob.job_id == job_id).first()
                if job:
                    job.status = "failed"
                    job.error = str(exc)[:1000]
                    db.commit()
            finally:
                db.close()

    def get_generation_job(self, job_id: str, user_id: str) -> dict | None:
        db = SessionLocal()
        try:
            job = db.query(RoadmapGenerationJob).filter(RoadmapGenerationJob.job_id == job_id, RoadmapGenerationJob.user_id == str(user_id)).first()
            if not job:
                return None
            return {"job_id": job.job_id, "status": job.status, "goal_id": job.goal_id, "error": job.error}
        finally:
            db.close()

    @staticmethod
    def _decode_roadmap(data: str) -> dict:
        try:
            roadmap = json.loads(data)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Saved roadmap data is invalid. Please regenerate the roadmap.") from exc
        if not isinstance(roadmap, dict):
            raise ValueError("Saved roadmap data is invalid. Please regenerate the roadmap.")
        roadmap = deduplicate_resources_across_phases(roadmap)
        ensure_phase_ids(roadmap)
        return roadmap

    @staticmethod
    def _preserve_phase_state(previous: dict, generated: dict) -> dict:
        """Preserve state only when title and skill content identify the same phase."""
        return preserve_phase_identity(previous, generated)

    @staticmethod
    def _reconcile_quiz_attempt_phases(db, user_id: str, goal_id: str, previous: dict, generated: dict) -> None:
        """Backfill legacy attempts and remap ordinals by stable phase identity after regeneration."""
        from app.db.models import QuizAttempt
        attempts = db.query(QuizAttempt).filter(QuizAttempt.user_id == str(user_id), QuizAttempt.goal_id == str(goal_id)).all()
        reconcile_attempts_to_phase_order(attempts, previous.get("phases", []) or [], generated.get("phases", []) or [])

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

        roadmap = deduplicate_resources_across_phases(roadmap)
        ensure_phase_ids(roadmap)
        return roadmap

    # ------------------------------------------------------------------
    # Roadmap generation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Prerequisite-aware planner (feature-flagged: USE_PATH_PLANNER)
    # ------------------------------------------------------------------

    @staticmethod
    def _prerequisite_depths(skill_ids, edges) -> dict:
        """Longest prerequisite chain below each skill (roots are 0).

        Used only as a deterministic tie-break so foundational skills are
        offered before skills that depend on long chains. Cycles are left at
        depth 0 here; ``SkillGraph`` rejects them with a clear error afterwards.
        """
        prereqs = {sid: set() for sid in skill_ids}
        dependents = {sid: set() for sid in skill_ids}
        for prerequisite, dependent in edges:
            if prerequisite in prereqs and dependent in prereqs and prerequisite != dependent:
                prereqs[dependent].add(prerequisite)
                dependents[prerequisite].add(dependent)
        indegree = {sid: len(p) for sid, p in prereqs.items()}
        depth = {sid: 0 for sid in prereqs}
        ready = [sid for sid, d in indegree.items() if d == 0]
        while ready:
            current = ready.pop()
            for nxt in dependents[current]:
                depth[nxt] = max(depth[nxt], depth[current] + 1)
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
        return depth

    def _build_plan(self, user_id: str, goal_id: str):
        """Return (plan, plan_phases) from the deterministic planner, or None
        when it cannot / should not be used (no goal skills in the catalogue,
        everything already mastered, or an invalid graph). Callers then fall
        back to the legacy generation path.

        Mastery comes from the goal-scoped BKT state, decayed by time since the
        last review. A skill the learner has recorded as known (``UserSkill``)
        but that has no goal-scoped state yet counts as mastered, which keeps
        the app's existing rule of not re-teaching recorded skills.
        """
        db = SessionLocal()
        try:
            target_ids = [gs.skill_id for gs in db.query(GoalSkill).filter(GoalSkill.goal_id == str(goal_id)).all()]
            if not target_ids:
                return None
            skills = {s.skill_id: s for s in db.query(Skill).all()}
            edges = [
                (d.prerequisite_id, d.skill_id)
                for d in db.query(SkillDependency).all()
                if d.prerequisite_id in skills and d.skill_id in skills
            ]
            mastery = {}
            for us in db.query(UserSkill).filter(UserSkill.user_id == str(user_id)).all():
                if us.skill_id in skills:
                    mastery[us.skill_id] = settings.PLANNER_STRONG_THRESHOLD
            last_reviewed = load_last_reviewed_at_by_skill(db, str(user_id), str(goal_id))
            for us in db.query(GoalUserSkill).filter(
                GoalUserSkill.user_id == str(user_id),
                GoalUserSkill.goal_id == str(goal_id),
            ).all():
                p = us.mastery_probability
                if p is None:
                    continue
                skill = skills.get(us.skill_id)
                last_at = last_reviewed.get(normalize_skill_name(skill.skill_name)) if skill else None
                p = decay_mastery(p, last_at)
                mastery[us.skill_id] = max(0.0, min(1.0, p))
        finally:
            db.close()

        depths = self._prerequisite_depths(list(skills), edges)
        graph = SkillGraph(
            [SkillNode(sid, sk.skill_name, difficulty=1 + depths.get(sid, 0)) for sid, sk in skills.items()],
            edges,
        )
        cfg = PlannerConfig(weak=settings.PLANNER_WEAK_THRESHOLD, strong=settings.PLANNER_STRONG_THRESHOLD)
        plan = plan_path(graph, [t for t in target_ids if t in skills], mastery, cfg)
        if not plan.items:
            return None
        plan_phases = [
            {
                "index": idx,
                "skills": [{"id": it.skill_id, "name": it.name, "action": it.action} for it in phase],
            }
            for idx, phase in enumerate(plan.phases)
        ]
        return plan, plan_phases

    def _build_llm_first_plan(
        self,
        user_id: str,
        goal_id: str,
        goal_name: str,
        learner: dict,
        *,
        restrict_to_goal_skills: bool = False,
    ):
        """Ask the LLM for a roadmap, then validate it against graph and mastery.

        For curated goals, ``restrict_to_goal_skills`` limits the validator graph
        to the goal's reviewed skill catalogue. This still enables LLM-first
        phase design while preventing unrelated edges in the legacy global graph
        from adding cross-domain prerequisites to a curated learning path.

        A missing target catalogue returns ``None`` so the established route can
        be used as a fallback. The original deterministic planner is not called
        before the proposal.
        """
        db = SessionLocal()
        try:
            # For curated goals, goal_curricula.json is the source of truth.
            # Do not depend on GoalSkill rows: local databases can have stale or
            # sparse mappings even when the reviewed curriculum is complete.
            # Read the full scope, including skills already recorded as known,
            # so goal-scoped mastery evidence can override global UserSkill data.
            if restrict_to_goal_skills:
                target_ids = curriculum_service.get_skill_ids(goal_id) or []
            else:
                target_ids = [
                    str(row.skill_id)
                    for row in db.query(GoalSkill).filter(GoalSkill.goal_id == str(goal_id)).all()
                ]
            target_ids = list(dict.fromkeys(str(sid) for sid in target_ids))
            if not target_ids:
                return None

            skill_rows = db.query(Skill).all()
            all_skills = {str(skill.skill_id): skill for skill in skill_rows}
            target_ids = [sid for sid in dict.fromkeys(target_ids) if sid in all_skills]
            if not target_ids:
                return None

            # Curated goal mappings align with the skill IDs in
            # dataset/goal_curricula.json. Keep these goals inside that reviewed
            # skill catalogue; only apply graph edges whose endpoints are both
            # in scope. Uncurated goals retain the full prerequisite closure.
            graph_skill_ids = set(target_ids) if restrict_to_goal_skills else set(all_skills)
            skills = {sid: all_skills[sid] for sid in graph_skill_ids}
            edges = [
                (str(dep.prerequisite_id), str(dep.skill_id))
                for dep in db.query(SkillDependency).all()
                if str(dep.prerequisite_id) in graph_skill_ids
                and str(dep.skill_id) in graph_skill_ids
            ]
            depths = self._prerequisite_depths(list(skills), edges)
            graph = SkillGraph(
                [
                    SkillNode(sid, skill.skill_name, difficulty=1 + depths.get(sid, 0))
                    for sid, skill in skills.items()
                ],
                edges,
            )

            mastery = {}
            for user_skill in db.query(UserSkill).filter(UserSkill.user_id == str(user_id)).all():
                if str(user_skill.skill_id) in skills:
                    # Preserve existing product semantics: a globally recorded
                    # skill is considered known unless goal-scoped quiz evidence
                    # overrides that value below.
                    mastery[str(user_skill.skill_id)] = settings.PLANNER_STRONG_THRESHOLD

            last_reviewed = load_last_reviewed_at_by_skill(db, str(user_id), str(goal_id))
            for state in db.query(GoalUserSkill).filter(
                GoalUserSkill.user_id == str(user_id),
                GoalUserSkill.goal_id == str(goal_id),
            ).all():
                sid = str(state.skill_id)
                if sid not in skills or state.mastery_probability is None:
                    continue
                last_at = last_reviewed.get(normalize_skill_name(skills[sid].skill_name))
                mastery[sid] = max(0.0, min(1.0, decay_mastery(state.mastery_probability, last_at)))

            allowed_ids = graph.closure(target_ids)
            candidate_skills = [
                {
                    "id": sid,
                    "name": skills[sid].skill_name,
                    "category": getattr(skills[sid], "category", "") or "",
                    "aliases": getattr(skills[sid], "aliases", "") or "",
                }
                for sid in sorted(allowed_ids, key=lambda value: (depths.get(value, 0), value))
            ]
            relevant_edges = [
                [prerequisite, dependent]
                for prerequisite, dependent in sorted(set(edges))
                if prerequisite in allowed_ids and dependent in allowed_ids
            ]
            mastery_context = {sid: float(mastery.get(sid, 0.0)) for sid in allowed_ids}
        finally:
            db.close()

        proposal = llm_service.generate_roadmap_proposal(
            goal_name=goal_name,
            learner=learner or {},
            target_skill_ids=target_ids,
            candidate_skills=candidate_skills,
            prerequisite_edges=relevant_edges,
            mastery_by_skill=mastery_context,
            weak_threshold=settings.PLANNER_WEAK_THRESHOLD,
            strong_threshold=settings.PLANNER_STRONG_THRESHOLD,
        )
        validation = validate_llm_roadmap_proposal(
            proposal,
            graph,
            target_ids,
            mastery,
            weak_threshold=settings.PLANNER_WEAK_THRESHOLD,
            strong_threshold=settings.PLANNER_STRONG_THRESHOLD,
        )
        logger.info(
            "LLM-first roadmap proposal validated: goal_id=%s proposed_phases=%d "
            "validated_phases=%d repaired=%s issues=%s",
            goal_id,
            len(proposal.get("phases", [])),
            len(validation["plan_phases"]),
            validation["repaired"],
            validation["issues"],
        )
        return {
            "proposal": proposal,
            "plan_phases": validation["plan_phases"],
            "repaired": validation["repaired"],
            "issues": validation["issues"],
            "missing_skills": [
                skill["name"]
                for phase in validation["plan_phases"]
                for skill in phase["skills"]
            ],
        }

    def _plan_for_uncurated_goal(self, user_id: str, goal_id: str):
        """Plan for a goal that has no curated curriculum.

        Returns ``(planned, fallback_plan, missing_skills)``. The evaluated
        prerequisite- and mastery-aware planner is tried first when
        ``USE_PATH_PLANNER`` is on (the default); the older possession-based
        topological plan is the backup if the planner is off, fails, or has
        nothing to plan. Raises ``ValueError`` if neither produces a plan.
        """
        planned = None
        if settings.USE_PATH_PLANNER:
            try:
                planned = self._build_plan(user_id, goal_id)
            except Exception as exc:
                logger.error(f"Path planner failed, using deterministic fallback: {exc}")
        if planned:
            return planned, None, [item.name for item in planned[0].items]

        fallback_plan = gap_analysis_service.get_fallback_plan(user_id)
        if not fallback_plan:
            raise ValueError(
                "No eligible skills are mapped to this goal. Add goal-skill "
                "mappings before generating a learning roadmap."
            )
        missing_skills = [
            skill["name"]
            for phase in fallback_plan
            for skill in phase["skills"]
        ]
        return None, fallback_plan, missing_skills

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

            # 2. Load the learner's recorded skills. Known goal curricula are
            # selected from dataset/goal_curricula.json rather than inferred
            # from the legacy dependency graph.
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

        # Keep each curated goal's reviewed skill scope, but allow the LLM-first
        # proposal + deterministic validation technique to design its phase
        # structure. For curated goals, the validator graph is scoped to the
        # goal's mapped skills so noisy cross-domain edges cannot expand scope.
        curated_plan = gap_analysis_service.get_curated_plan(user_id)
        fallback_plan = None
        planned = None
        llm_first_plan = None
        learner_context = {
            "experience_level": user_profile.get("experience_level"),
            "available_hours_per_week": user_profile.get("available_hours_per_week"),
            "learning_style": user_profile.get("learning_style"),
        }

        if settings.USE_LLM_FIRST_VALIDATED_ROADMAP:
            try:
                llm_first_plan = self._build_llm_first_plan(
                    user_id,
                    goal_id,
                    goal_name,
                    learner_context,
                    restrict_to_goal_skills=curated_plan is not None,
                )
            except Exception as exc:
                # Preserve a safe fallback when proposal generation or
                # validation fails. A curated curriculum takes precedence over
                # the generic planner because it has a reviewed skill scope.
                logger.warning(
                    "LLM-first roadmap path failed; falling back to the existing plan: %s",
                    exc,
                )

        if llm_first_plan:
            missing_skills = llm_first_plan["missing_skills"]
        elif curated_plan is not None:
            missing_skills = [
                skill["name"]
                for phase in curated_plan
                for skill in phase["skills"]
            ]
            if not curated_plan:
                raise ValueError(
                    "No unlearned skills remain in this goal's curriculum. "
                    "Choose another goal or update your recorded skills before generating a new roadmap."
                )
        else:
            planned, fallback_plan, missing_skills = self._plan_for_uncurated_goal(user_id, goal_id)

        selected_plan = (
            (llm_first_plan["plan_phases"] if llm_first_plan else None)
            or curated_plan
            or (planned[1] if planned else fallback_plan)
            or []
        )
        selected_mode = (
            "llm-proposal-validated" if llm_first_plan else
            "curated" if curated_plan is not None else
            "graph-planner" if planned else
            "deterministic-fallback"
        )
        logger.info(
            "Roadmap plan selected: goal_id=%s mode=%s phases=%d skills=%d titles=%s",
            goal_id,
            selected_mode,
            len(selected_plan),
            sum(len(phase.get("skills", [])) for phase in selected_plan),
            [phase.get("title", "") for phase in selected_plan],
        )

        # 3. Retrieve resource candidates separately for every planned phase.
        # The previous implementation searched only the first eight skills and
        # put every result in one global pool; that starved later phases and
        # let the LLM reuse early-phase links elsewhere.
        try:
            raw_resources_by_phase = web_search_service.search_courses_for_plan(
                selected_plan
            )
        except Exception as exc:
            logger.error(
                "Phase-scoped live resource search failed; continuing without "
                "unverified links: %s",
                exc,
            )
            raw_resources_by_phase = {}

        verified_resources_by_phase = {}
        for position, planned_phase in enumerate(selected_plan):
            try:
                phase_index = int(planned_phase.get("index", position))
            except (TypeError, ValueError):
                phase_index = position
            phase_skills = [
                str(skill.get("name") or skill.get("id") or "").strip()
                if isinstance(skill, dict) else str(skill).strip()
                for skill in planned_phase.get("skills", [])
            ]
            phase_candidates = raw_resources_by_phase.get(phase_index, [])
            phase_resources = filter_relevant_resources(
                phase_candidates,
                phase_skills,
                verified_resources=phase_candidates,
                limit=3,
            )
            # Preserve the matching-skill annotation only in prompt context;
            # the user-facing resource schema remains title/url/type.
            raw_by_url = {item.get("url"): item for item in phase_candidates if item.get("url")}
            verified_resources_by_phase[phase_index] = [
                {
                    **resource,
                    "matched_skill": raw_by_url.get(resource.get("url"), {}).get("matched_skill", ""),
                    "phase_index": phase_index,
                }
                for resource in phase_resources
            ]
            logger.info(
                "Resource audit: phase_index=%s title=%s candidates=%d approved=%d",
                phase_index,
                planned_phase.get("title", ""),
                len(phase_candidates),
                len(phase_resources),
            )

        verified_live_resources = [
            resource
            for phase_resources in verified_resources_by_phase.values()
            for resource in phase_resources
        ]

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
            "verified_live_resources": verified_live_resources,
            "verified_resources_by_phase": verified_resources_by_phase,
            "goal_skill_name": goal_name,
        }

        # The LLM-first path is now the default for both curated and uncurated
        # goals. Curated goals remain scoped to their reviewed skill catalogue;
        # uncurated goals use the graph's prerequisite closure. If structural
        # repairs changed phase membership/order, elaborate the corrected plan;
        # otherwise preserve project metadata from the initial proposal.
        if llm_first_plan:
            if llm_first_plan["repaired"]:
                roadmap_dict = llm_service.generate_roadmap_from_plan(
                    context, llm_first_plan["plan_phases"]
                )
            else:
                roadmap_dict = llm_service.merge_proposal_with_validated_plan(
                    llm_first_plan["proposal"], llm_first_plan["plan_phases"]
                )
        elif curated_plan is not None:
            roadmap_dict = llm_service.generate_roadmap_from_plan(context, curated_plan)
        elif planned:
            roadmap_dict = llm_service.generate_roadmap_from_plan(context, planned[1])
        elif fallback_plan:
            roadmap_dict = llm_service.generate_roadmap_from_plan(context, fallback_plan)
        else:
            raise ValueError("No valid learning plan could be constructed for this goal.")

        # A structural repair can cause the second elaboration call to omit
        # projects even though the original proposal contained good ideas.
        # Restore proposal projects by skill overlap first, then guarantee a
        # concrete project for every phase as a last-resort fallback.
        if llm_first_plan and llm_first_plan["repaired"]:
            roadmap_dict = llm_service.preserve_proposal_projects(
                llm_first_plan.get("proposal"),
                llm_first_plan.get("plan_phases", []),
                roadmap_dict,
            )
        roadmap_dict = llm_service.ensure_project_ideas(roadmap_dict)

        # The frontend needs the goal ID immediately
        # after generating a new roadmap.
        if isinstance(roadmap_dict, dict):
            roadmap_dict["goal_id"] = goal_id

        # 5.5 Assign resources from the phase-specific, URL-verified retrieval
        # pool. Do not trust the LLM to pick URLs across phases: its resource
        # fields are discarded and replaced with vetted search results only.
        if isinstance(roadmap_dict, dict):
            generated_phases = roadmap_dict.get("phases", []) or []
            for position, phase in enumerate(generated_phases):
                planned_phase = selected_plan[position] if position < len(selected_plan) else {}
                try:
                    phase_index = int(planned_phase.get("index", position))
                except (TypeError, ValueError):
                    phase_index = position
                approved = verified_resources_by_phase.get(phase_index, [])
                phase["resources"] = [
                    {
                        "title": resource.get("title", ""),
                        "url": resource.get("url", ""),
                        "type": resource.get("type", "article"),
                    }
                    for resource in approved
                ]
                logger.info(
                    "Resource assignment: phase_index=%s title=%s resources=%d",
                    phase_index,
                    phase.get("title", ""),
                    len(phase["resources"]),
                )

        # 5.6 Normalize any study notes that may already
        # exist in generated data.
        roadmap_dict = self._normalize_roadmap(
            roadmap_dict
        )

        if isinstance(roadmap_dict, dict):
            roadmap_dict = RoadmapResponse.model_validate(roadmap_dict).model_dump(exclude_none=True)

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
                    learning_features_service.record_version(db, existing, existing.data)
                    previous_roadmap = self._decode_roadmap(existing.data)
                    roadmap_dict = self._preserve_phase_state(previous_roadmap, roadmap_dict)
                    self._reconcile_quiz_attempt_phases(db, user_id, goal_id, previous_roadmap, roadmap_dict)
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

            except Exception as exc:
                db.rollback()
                raise RuntimeError("The roadmap was generated but could not be saved.") from exc

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

            roadmap = self._decode_roadmap(row.data)

            roadmap["goal_id"] = row.goal_id

            # Repair malformed study notes already stored
            # in the database.
            original_data = row.data

            roadmap = self._normalize_roadmap(
                roadmap
            )

            for phase in roadmap.get("phases", []) or []:
                phase["resources"] = filter_relevant_resources(
                    phase.get("resources", []), phase.get("skills", [])
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

    
    def delete_roadmap(self, user_id: str, goal_id: str) -> bool:
        db = SessionLocal()
        try:
            row = (
                db.query(Roadmap)
                .filter(
                    Roadmap.user_id == str(user_id),
                    Roadmap.goal_id == str(goal_id),
                )
                .first()
            )

            if not row:
                return False

            db.query(RoadmapVersion).filter(
                RoadmapVersion.roadmap_id == row.id
            ).delete(synchronize_session=False)

            db.delete(row)
            db.commit()
            return True

        except Exception:
            db.rollback()
            raise

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

            roadmap = self._decode_roadmap(row.data)

            phases = roadmap.get(
                "phases",
                [],
            )

            if not 0 <= phase_index < len(phases):
                return None
            phases[phase_index]["completed"] = completed

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

            roadmap = self._decode_roadmap(row.data)

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

    def complete_roadmap(self, user_id: str, goal_id: str):
        """Mark a fully completed roadmap and initialize explicit goal mastery.

        Completion alone is not quiz evidence, so a skill with no labelled
        responses receives the configured BKT prior and zero observations.
        """
        db = SessionLocal()
        try:
            row = db.query(Roadmap).filter(
                Roadmap.user_id == str(user_id),
                Roadmap.goal_id == str(goal_id),
            ).first()
            if not row:
                return None

            roadmap = self._decode_roadmap(row.data)
            phases = roadmap.get("phases", []) or []
            if not phases or not all(phase.get("completed") for phase in phases):
                raise ValueError("Complete every roadmap phase before marking the roadmap complete.")

            roadmap["is_complete"] = True
            row.data = json.dumps(roadmap)
            row.is_complete = True
            params = get_bkt_parameters(db)
            learned_skills = {
                str(skill).strip()
                for phase in phases
                for skill in (phase.get("skills", []) or [])
                if str(skill).strip()
            }
            history_rows = (
                db.query(
                    QuizQuestionHistory.skill_name,
                    QuizQuestionHistory.is_correct,
                    QuizAttempt.created_at,
                    QuizQuestionHistory.question_index,
                    QuizQuestionHistory.id,
                )
                .join(QuizAttempt, QuizQuestionHistory.attempt_id == QuizAttempt.id)
                .filter(
                    QuizAttempt.user_id == str(user_id),
                    QuizAttempt.goal_id == str(goal_id),
                    QuizQuestionHistory.skill_name.isnot(None),
                )
                .order_by(QuizAttempt.created_at, QuizQuestionHistory.question_index, QuizQuestionHistory.id)
                .all()
            )
            evidence_by_skill = {}
            for recorded_name, is_correct, *_ in history_rows:
                key = normalize_skill_name(recorded_name)
                if key:
                    evidence_by_skill.setdefault(key, []).append(bool(is_correct))

            for skill_name in learned_skills:
                skill = db.query(Skill).filter(Skill.skill_name.ilike(skill_name)).first()
                if skill is None:
                    skill = Skill(
                        skill_id=str(uuid.uuid4()),
                        skill_name=skill_name,
                        category="Learned from Roadmap",
                    )
                    db.add(skill)
                    db.flush()

                # UserSkill remains the global possessed-skill/profile record;
                # its mastery fields are no longer used for BKT decisions.
                profile_skill = db.query(UserSkill).filter(
                    UserSkill.user_id == str(user_id),
                    UserSkill.skill_id == str(skill.skill_id),
                ).first()
                if profile_skill is None:
                    db.add(UserSkill(
                        user_id=str(user_id),
                        skill_id=str(skill.skill_id),
                        proficiency=1,
                        mastery_probability=None,
                        bkt_observations=0,
                    ))

                goal_skill = db.query(GoalUserSkill).filter(
                    GoalUserSkill.user_id == str(user_id),
                    GoalUserSkill.goal_id == str(goal_id),
                    GoalUserSkill.skill_id == str(skill.skill_id),
                ).first()
                historical = evidence_by_skill.get(normalize_skill_name(skill.skill_name), [])
                initial = params.p_initial
                observations = 0
                if historical:
                    # Recover older per-question evidence in this goal only.
                    from app.services.skill_extraction import skill_extraction_service
                    for was_correct in historical:
                        initial = skill_extraction_service.bkt_update(
                            initial, was_correct,
                            p_learn=params.p_learn, p_guess=params.p_guess, p_slip=params.p_slip,
                        )
                    observations = len(historical)

                if goal_skill is None:
                    db.add(GoalUserSkill(
                        user_id=str(user_id),
                        goal_id=str(goal_id),
                        skill_id=str(skill.skill_id),
                        proficiency=max(1, min(5, math.ceil(initial * 5))),
                        mastery_probability=initial,
                        bkt_observations=observations,
                    ))
                elif (goal_skill.bkt_observations or 0) == 0 and observations:
                    goal_skill.mastery_probability = initial
                    goal_skill.proficiency = max(1, min(5, math.ceil(initial * 5)))
                    goal_skill.bkt_observations = observations
                elif goal_skill.mastery_probability is None:
                    goal_skill.mastery_probability = params.p_initial
                    goal_skill.proficiency = max(1, min(5, math.ceil(params.p_initial * 5)))
                    goal_skill.bkt_observations = goal_skill.bkt_observations or 0

            db.commit()
            activity_service.log_activity(user_id, "roadmap_completed")
            return roadmap
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()



roadmap_service = RoadmapService()