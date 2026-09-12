import pandas as pd
import os
from threading import Lock
from .config import settings
from .logger import logger

class CSVHandler:
    def __init__(self):
        self._locks = {}
        self.dataset_dir = settings.DATASET_DIR
        
        # Initialize default datasets if they don't exist
        self._initialize_datasets()

    def _get_lock(self, filename: str) -> Lock:
        if filename not in self._locks:
            self._locks[filename] = Lock()
        return self._locks[filename]

    def _initialize_datasets(self):
        # Define necessary columns for each file
        datasets = {
            "users.csv": ["user_id", "email", "hashed_password", "goal_id", "experience_level", "available_hours_per_week", "learning_style"],
            "skills.csv": ["skill_id", "skill_name", "category"],
            "skill_dependencies.csv": ["skill_id", "prerequisite_id"],
            "goals.csv": ["goal_id", "goal_name"],
            "goal_skills.csv": ["goal_id", "skill_id", "importance"], # importance could be 1-5
            "resources.csv": ["resource_id", "skill_id", "title", "url", "type", "difficulty"],
            "projects.csv": ["project_id", "title", "description", "skills_covered", "difficulty"],
            "user_skills.csv": ["user_id", "skill_id", "proficiency"], # proficiency 1-5
            "user_feedback.csv": ["feedback_id", "user_id", "content_id", "content_type", "rating", "comments"]
        }
        
        for filename, cols in datasets.items():
            filepath = os.path.join(self.dataset_dir, filename)
            if not os.path.exists(filepath):
                pd.DataFrame(columns=cols).to_csv(filepath, index=False)
                logger.info(f"Initialized {filename}")

    def read_csv(self, filename: str) -> pd.DataFrame:
        filepath = os.path.join(self.dataset_dir, filename)
        with self._get_lock(filename):
            try:
                datasets = self._get_dataset_columns()
                cols = datasets.get(filename, [])
                
                # Handle nonempty files
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    df = pd.read_csv(filepath)
                    
                    # Backwards compatibility check
                    if filename == 'users.csv' and 'preferred_learning_style' in df.columns:
                        df.rename(columns={'preferred_learning_style': 'learning_style'}, inplace=True)
                        
                    # Inject any missing columns
                    for c in cols:
                        if c not in df.columns:
                            df[c] = ""
                    return df
                
                # Fallback to column initialization structure if file is empty/nonexistent
                return pd.DataFrame(columns=cols)
            except Exception as e:
                logger.error(f"Error reading {filename}: {e}")
                return pd.DataFrame()

    def write_csv(self, filename: str, df: pd.DataFrame):
        filepath = os.path.join(self.dataset_dir, filename)
        with self._get_lock(filename):
            try:
                df.to_csv(filepath, index=False)
                logger.debug(f"Successfully wrote to {filename}")
            except Exception as e:
                logger.error(f"Error writing to {filename}: {e}")

    def append_row(self, filename: str, row_dict: dict):
        df = self.read_csv(filename)
        new_row = pd.DataFrame([row_dict])
        df = pd.concat([df, new_row], ignore_index=True)
        self.write_csv(filename, df)

    def _get_dataset_columns(self):
         return {
            "users.csv": ["user_id", "username", "email", "hashed_password", "goal_id", "experience_level", "available_hours_per_week", "learning_style"],
            "skills.csv": ["skill_id", "skill_name", "category"],
            "skill_dependencies.csv": ["skill_id", "prerequisite_id"],
            "goals.csv": ["goal_id", "goal_name"],
            "goal_skills.csv": ["goal_id", "skill_id", "importance"],
            "resources.csv": ["resource_id", "skill_id", "title", "url", "type", "difficulty"],
            "projects.csv": ["project_id", "title", "description", "skills_covered", "difficulty"],
            "user_skills.csv": ["user_id", "skill_id", "proficiency"],
            "user_feedback.csv": ["feedback_id", "user_id", "content_id", "content_type", "rating", "comments"]
        }

csv_handler = CSVHandler()
