import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Personalized Learning Path Generator"
    
    # JWT Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 1 week
    
    # Paths
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATASET_DIR: str = os.path.join(os.path.dirname(BASE_DIR), "dataset")
    APP_DATA_DIR: str = os.path.join(BASE_DIR, "data")

    # Database (replaces the old CSV-file storage; DATASET_DIR above is now only
    # used by scripts/migrate_csv_to_db.py to import the old data one time)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "learning_path.db"
        ),
    )
    
    # LLM Settings
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    GROQ_TIMEOUT_SECONDS: int = 60
    ENABLE_HF_FALLBACK: bool = False
    HF_FALLBACK_MODEL: str = "HuggingFaceH4/zephyr-7b-beta"
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    
    # Embeddings
    EMBEDDINGS_MODEL: str = "all-MiniLM-L6-v2"

    # Password reset (forgot-password feature). If SMTP_HOST is left empty,
    # the reset link is logged instead of emailed — fine for local dev.
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "no-reply@learningpath.local")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30

    class Config:
        env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")

settings = Settings()

# Ensure directories exist
os.makedirs(settings.DATASET_DIR, exist_ok=True)
os.makedirs(settings.APP_DATA_DIR, exist_ok=True)
