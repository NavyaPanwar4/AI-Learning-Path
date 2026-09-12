from app.utils.csv_handler import csv_handler

class GapAnalysisService:
    def identify_missing_skills(self, user_id: str) -> list:
        # Load user
        users_df = csv_handler.read_csv("users.csv")
        user_row = users_df[users_df['user_id'] == user_id]
        if user_row.empty:
            return []
        goal_id = user_row.iloc[0].get('goal_id')
        
        # Current skills
        user_skills_df = csv_handler.read_csv("user_skills.csv")
        current_skill_ids = []
        if not user_skills_df.empty:
            current_skill_ids = user_skills_df[user_skills_df['user_id'] == user_id]['skill_id'].tolist()
            
        # Target skills for goal
        goal_skills_df = csv_handler.read_csv("goal_skills.csv")
        target_skill_ids = []
        if not goal_skills_df.empty and goal_id:
            target_skill_ids = goal_skills_df[goal_skills_df['goal_id'] == goal_id]['skill_id'].tolist()
            
        # If no goal is set or goal has no skills, return empty
        if not target_skill_ids:
            return []
            
        # Find missing directly
        missing_skill_ids = set(target_skill_ids) - set(current_skill_ids)
        
        # Enforce dependencies (if a missing skill has prerequisites, add them)
        deps_df = csv_handler.read_csv("skill_dependencies.csv")
        if not deps_df.empty:
            added_deps = True
            while added_deps:
                added_deps = False
                for ms_id in list(missing_skill_ids):
                    reqs = deps_df[deps_df['skill_id'] == ms_id]['prerequisite_id'].tolist()
                    for req in reqs:
                        if req not in current_skill_ids and req not in missing_skill_ids:
                            missing_skill_ids.add(req)
                            added_deps = True
                            
        # Map IDs to Names
        skills_df = csv_handler.read_csv("skills.csv")
        missing_skill_names = []
        if not skills_df.empty:
            for ms_id in missing_skill_ids:
                matches = skills_df[skills_df['skill_id'] == ms_id]
                if not matches.empty:
                    missing_skill_names.append(matches.iloc[0]['skill_name'])
                    
        return missing_skill_names

gap_analysis_service = GapAnalysisService()
