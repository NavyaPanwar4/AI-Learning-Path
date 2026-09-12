from typing import List, Dict
from rapidfuzz import process, fuzz
from app.services.llm_service import llm_service
from app.utils.csv_handler import csv_handler
from app.models.schemas import ExtractedSkill
import uuid
import pandas as pd

class SkillExtractionService:
    def _fuzzy_match_list(self, skill_list, master_skills, skills_df):
        matched_results = []
        for skill in skill_list:
            skill_name = skill.get("skill_name", "")
            confidence = skill.get("confidence", 0.8)
            
            best_match_id = None
            if master_skills and skill_name:
                choices = list(master_skills.keys())
                match = process.extractOne(skill_name, choices, scorer=fuzz.token_set_ratio)
                
                if match and match[1] >= 75:
                    best_match_string = match[0]
                    best_match_id = str(master_skills[best_match_string])
                    
                    primary_row = skills_df[skills_df['skill_id'].astype(str) == best_match_id]
                    if not primary_row.empty:
                        skill_name = primary_row.iloc[0]['skill_name']
                    else:
                        skill_name = best_match_string
            
            if not best_match_id and skill_name:
                best_match_id = str(uuid.uuid4())
                csv_handler.append_row("skills.csv", {
                    "skill_id": best_match_id,
                    "skill_name": skill_name,
                    "category": "Extracted"
                })
                master_skills[skill_name] = best_match_id
            
            if best_match_id:
                matched_results.append(ExtractedSkill(
                    skill_name=skill_name,
                    matched_skill_id=best_match_id,
                    confidence=confidence
                ))
        return matched_results

    def extract_and_match(self, user_id: str, free_text: str) -> Dict[str, List[ExtractedSkill]]:
        # 1. Ask LLM to extract skills from free_text
        llm_response = llm_service.extract_skills(free_text)
        extracted = llm_response.get("extracted_skills", [])
        desired = llm_response.get("desired_skills", [])
        
        # 2. Get master skills list
        skills_df = csv_handler.read_csv("skills.csv")
        master_skills = {}
        if not skills_df.empty:
            for _, row in skills_df.iterrows():
                sid = str(row['skill_id'])
                master_skills[row['skill_name']] = sid
                if 'aliases' in row and pd.notna(row['aliases']) and str(row['aliases']).strip():
                    for alias in str(row['aliases']).split(','):
                        if alias.strip():
                            master_skills[alias.strip()] = sid
                            
        # 3. Fuzzy match
        matched_extracted = self._fuzzy_match_list(extracted, master_skills, skills_df)
        matched_desired = self._fuzzy_match_list(desired, master_skills, skills_df)
        
        # Store securely to user_skills.csv only for known possessed skills
        user_skills_df = csv_handler.read_csv("user_skills.csv")
        for es in matched_extracted:
            exists = False
            if not user_skills_df.empty:
                exists = not user_skills_df[
                    (user_skills_df['user_id'] == str(user_id)) & 
                    (user_skills_df['skill_id'] == es.matched_skill_id)
                ].empty
                
            if not exists:
                csv_handler.append_row("user_skills.csv", {
                    "user_id": user_id,
                    "skill_id": es.matched_skill_id,
                    "proficiency": 1 
                })
                user_skills_df = csv_handler.read_csv("user_skills.csv")
                    
        return {
            "extracted_skills": matched_extracted,
            "desired_skills": matched_desired
        }

skill_extraction_service = SkillExtractionService()
