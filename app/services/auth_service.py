import uuid
import pandas as pd
from typing import Optional
from app.utils.csv_handler import csv_handler
from app.utils.security import get_password_hash, verify_password, create_access_token
from app.models.schemas import UserCreate, UserLogin, Token

class AuthService:
    def register_user(self, user_data: UserCreate) -> Token:
        users_df = csv_handler.read_csv("users.csv")
        
        if not users_df.empty:
            if user_data.email in users_df["email"].values:
                raise ValueError("Email already registered")
            if "username" in users_df.columns and user_data.username in users_df["username"].values:
                raise ValueError("Username already taken")
            
        user_id = str(uuid.uuid4())
        hashed_password = get_password_hash(user_data.password)
        
        new_user = {
            "user_id": user_id,
            "username": user_data.username,
            "email": user_data.email,
            "hashed_password": hashed_password,
            "goal_id": "",
            "experience_level": "",
            "available_hours_per_week": 10,
            "learning_style": ""
        }
        
        csv_handler.append_row("users.csv", new_user)
        
        access_token = create_access_token(data={"sub": user_id})
        return Token(access_token=access_token, token_type="bearer")

    def authenticate_user(self, user_login: UserLogin) -> Token:
        users_df = csv_handler.read_csv("users.csv")
        
        if users_df.empty:
             raise ValueError("User not found")
             
        # Find user by email OR username
        user_row = users_df[(users_df["email"] == user_login.username) | (users_df["username"] == user_login.username)]
        
        if user_row.empty:
            raise ValueError("Incorrect username/email or password")
            
        user = user_row.iloc[0]
        if not verify_password(user_login.password, user["hashed_password"]):
            raise ValueError("Invalid credentials")
            
        access_token = create_access_token(data={"sub": str(user["user_id"])})
        return Token(access_token=access_token, token_type="bearer")

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        users_df = csv_handler.read_csv("users.csv")
        if users_df.empty:
            return None
        user_row = users_df[users_df["user_id"] == user_id]
        if user_row.empty:
            return None
        user_dict = user_row.iloc[0].to_dict()
        return {k: (v if pd.notna(v) else None) for k, v in user_dict.items()}

    def update_user_profile(self, user_id: str, profile_data):
        users_df = csv_handler.read_csv("users.csv")
        if users_df.empty:
            raise ValueError("No users database found")
            
        mask = users_df["user_id"].astype(str) == str(user_id)
        if not mask.any():
            raise ValueError("User not found")
            
        users_df.loc[mask, "goal_id"] = profile_data.goal_id
        users_df.loc[mask, "experience_level"] = profile_data.experience_level
        users_df.loc[mask, "available_hours_per_week"] = profile_data.available_hours_per_week
        users_df.loc[mask, "learning_style"] = profile_data.learning_style
        
        csv_handler.write_csv("users.csv", users_df)
        return {"status": "success", "message": "Profile updated successfully."}
        
    def get_all_goals(self) -> list:
        goals_df = csv_handler.read_csv("goals.csv")
        if goals_df.empty:
            return []
        
        # safely handle NaNs with generic strings before returning
        return goals_df.fillna("None").to_dict('records')

auth_service = AuthService()
