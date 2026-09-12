from app.services.gap_analysis import gap_analysis_service
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service
from app.services.web_search_service import web_search_service
from app.services.auth_service import auth_service
from app.utils.config import settings
from app.utils.csv_handler import csv_handler
import os
import json

class RoadmapService:
    def generate_personalized_roadmap(self, user_id: str):
        # 1. Load user profile
        user_profile = auth_service.get_user_by_id(user_id)
        if not user_profile:
            raise ValueError("User not found")
            
        # 1.5 Check Cache
        goal_id = str(user_profile.get("goal_id", "default"))
        
        goal_name = "Unknown Goal"
        goals_df = csv_handler.read_csv("goals.csv")
        if not goals_df.empty:
            matches = goals_df[goals_df["goal_id"].astype(str) == goal_id]
            if not matches.empty:
                goal_name = matches.iloc[0]["goal_name"]
                
        cache_file = os.path.join(settings.APP_DATA_DIR, f"{user_id}_{goal_id}_roadmap.json")
        # 2. Identify missing skills
        missing_skills = gap_analysis_service.identify_missing_skills(user_id)
        
        # 2.5 Identify possessed skills for LLM acknowledgement
        user_skills_df = csv_handler.read_csv("user_skills.csv")
        possessed_skill_ids = []
        if not user_skills_df.empty:
            possessed_skill_ids = user_skills_df[user_skills_df['user_id'] == str(user_id)]['skill_id'].tolist()
            
        skills_df = csv_handler.read_csv("skills.csv")
        possessed_skills = []
        if not skills_df.empty:
            for sid in possessed_skill_ids:
                matches = skills_df[skills_df['skill_id'].astype(str) == str(sid)]
                if not matches.empty:
                    possessed_skills.append(matches.iloc[0]['skill_name'])
        
        # 3. Retrieve RAG context
        rag_context = rag_service.retrieve_context(missing_skills)
        
        # 3.5 Retrieve live web resources (Agentic Research)
        try:
            live_resources = web_search_service.search_courses(missing_skills)
            if live_resources:
                if "resources" not in rag_context:
                    rag_context["resources"] = []
                rag_context["resources"].extend(live_resources)
        except Exception:
            pass # fail gracefully if web search fails
        
        # 4. Construct Context for LLM
        context = {
            "experience_level": user_profile.get("experience_level"),
            "available_hours_per_week": user_profile.get("available_hours_per_week"),
            "learning_style": user_profile.get("learning_style"),
            "missing_skills": missing_skills,
            "possessed_skills": possessed_skills,
            "resources": rag_context.get("resources", []),
            "projects": rag_context.get("projects", []),
            "goal_skill_name": goal_name
        }
        
        # 5. Generate Roadmap via LLM
        roadmap_dict = llm_service.generate_roadmap(context)
        
        # Inject goal_id for frontend tracking
        if isinstance(roadmap_dict, dict):
            roadmap_dict["goal_id"] = goal_id

        # 6. Save to Cache
        if roadmap_dict and (roadmap_dict.get("phases") or roadmap_dict.get("roadmap_text")):
            try:
                with open(cache_file, "w") as f:
                    json.dump(roadmap_dict, f)
            except Exception:
                pass
        
        return roadmap_dict

    def get_saved_roadmaps(self, user_id: str):
        goals_df = csv_handler.read_csv("goals.csv")
        saved = []
        if not os.path.exists(settings.APP_DATA_DIR):
            return saved
        for filename in os.listdir(settings.APP_DATA_DIR):
            if filename.startswith(f"{user_id}_") and filename.endswith("_roadmap.json"):
                parts = filename.split("_")
                if len(parts) >= 3:
                    goal_id = parts[1]
                    goal_name = "Unknown Goal"
                    if not goals_df.empty:
                        matches = goals_df[goals_df["goal_id"].astype(str) == goal_id]
                        if not matches.empty:
                            goal_name = matches.iloc[0]["goal_name"]
                            
                    is_complete = False
                    try:
                        roadmap_path = os.path.join(settings.APP_DATA_DIR, filename)
                        with open(roadmap_path, "r") as f:
                            rdata = json.load(f)
                            is_complete = rdata.get("is_complete", False)
                    except Exception:
                        pass
                        
                    saved.append({"goal_id": goal_id, "goal_name": goal_name, "is_complete": is_complete})
        return saved

    def get_saved_roadmap(self, user_id: str, goal_id: str):
        cache_file = os.path.join(settings.APP_DATA_DIR, f"{user_id}_{goal_id}_roadmap.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                return json.load(f)
        return None

    def update_phase_status(self, user_id: str, goal_id: str, phase_index: int, completed: bool):
        cache_file = os.path.join(settings.APP_DATA_DIR, f"{user_id}_{goal_id}_roadmap.json")
        if not os.path.exists(cache_file):
            return None
        
        with open(cache_file, "r") as f:
            roadmap = json.load(f)
        
        phases = roadmap.get("phases", [])
        if 0 <= phase_index < len(phases):
            phases[phase_index]["completed"] = completed
            
        with open(cache_file, "w") as f:
            json.dump(roadmap, f)
            
        return roadmap

    def generate_phase_study_notes(self, user_id: str, goal_id: str, phase_index: int):
        """Generate and persist notes so learners do not pay for the same phase twice."""
        cache_file = os.path.join(settings.APP_DATA_DIR, f"{user_id}_{goal_id}_roadmap.json")
        if not os.path.exists(cache_file):
            return None

        with open(cache_file, "r") as f:
            roadmap = json.load(f)

        phases = roadmap.get("phases", [])
        if not 0 <= phase_index < len(phases):
            return None

        phase = phases[phase_index]
        if phase.get("ai_notes"):
            return phase["ai_notes"]

        profile = auth_service.get_user_by_id(user_id) or {}
        notes = llm_service.generate_study_notes(
            phase_title=phase.get("title", f"Phase {phase_index + 1}"),
            skills=phase.get("skills", []),
            duration=phase.get("duration", "At your own pace"),
            experience_level=profile.get("experience_level", "beginner"),
        )
        required_fields = {"title", "overview"}
        if not notes or not required_fields.issubset(notes):
            raise ValueError("Groq could not generate study notes. Please try again.")

        phase["ai_notes"] = notes
        with open(cache_file, "w") as f:
            json.dump(roadmap, f)
        return notes

    def complete_roadmap(self, user_id: str, goal_id: str):
        cache_file = os.path.join(settings.APP_DATA_DIR, f"{user_id}_{goal_id}_roadmap.json")
        if not os.path.exists(cache_file):
            return None
            
        with open(cache_file, "r") as f:
            roadmap = json.load(f)
            
        roadmap["is_complete"] = True
        
        with open(cache_file, "w") as f:
            json.dump(roadmap, f)
            
        # Add learned skills
        try:
            learned_skills = set()
            for phase in roadmap.get("phases", []):
                for skill in phase.get("skills", []):
                    learned_skills.add(skill)
                    
            if learned_skills:
                skills_df = csv_handler.read_csv("skills.csv")
                user_skills_df = csv_handler.read_csv("user_skills.csv")
                
                for skill_name in learned_skills:
                    # 1. find or create skill_id
                    match = None
                    if not skills_df.empty and 'skill_name' in skills_df.columns:
                        match = skills_df[skills_df['skill_name'].astype(str).str.lower() == str(skill_name).lower()]
                        
                    if match is not None and not match.empty:
                        skill_id = str(match.iloc[0]['skill_id'])
                    else:
                        import uuid
                        skill_id = str(uuid.uuid4())
                        csv_handler.append_row("skills.csv", {
                            "skill_id": skill_id,
                            "skill_name": str(skill_name),
                            "category": "Learned from Roadmap"
                        })
                        skills_df = csv_handler.read_csv("skills.csv")
                        
                    # 2. Add to user_skills if not exists
                    exists = False
                    if not user_skills_df.empty:
                        exists = not user_skills_df[(user_skills_df['user_id'].astype(str) == str(user_id)) & (user_skills_df['skill_id'].astype(str) == skill_id)].empty
                        
                    if not exists:
                        csv_handler.append_row("user_skills.csv", {
                            "user_id": str(user_id),
                            "skill_id": skill_id,
                            "proficiency": 1
                        })
                        user_skills_df = csv_handler.read_csv("user_skills.csv")
        except Exception as e:
            from app.utils.logger import logger
            logger.error(f"Error adding learned skills on roadmap completion: {e}")
            
        return roadmap

roadmap_service = RoadmapService()
