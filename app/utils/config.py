import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Traject"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    # Legacy compatibility setting; application startup does not run create_all.
    AUTO_CREATE_SCHEMA: bool = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true"
    RATE_LIMIT_REDIS_URL: str = os.getenv("RATE_LIMIT_REDIS_URL", "")
    WEB_SEARCH_CACHE_TTL_SECONDS: int = int(os.getenv("WEB_SEARCH_CACHE_TTL_SECONDS", "86400"))
    ADMIN_EMAILS: str = os.getenv("ADMIN_EMAILS", "")

    # JWT Auth
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 week

    youtube_api_key: str = os.getenv(
        "YOUTUBE_API_KEY",
        "",
    )

    # Paths
    BASE_DIR: str = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    DATASET_DIR: str = os.path.join(
        os.path.dirname(BASE_DIR),
        "dataset",
    )
    APP_DATA_DIR: str = os.path.join(
        BASE_DIR,
        "data",
    )

    # Database (replaces the old CSV-file storage; DATASET_DIR above is now
    # only used by scripts/migrate_csv_to_db.py to import the old data one time)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///"
        + os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)
                )
            ),
            "data",
            "learning_path.db",
        ),
    )

    # Groq-hosted LLM (primary provider for chat and structured generation)
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    GROQ_TIMEOUT_SECONDS: int = int(os.getenv("GROQ_TIMEOUT_SECONDS", "60"))
    GROQ_QUIZ_TIMEOUT_SECONDS: int = int(os.getenv("GROQ_QUIZ_TIMEOUT_SECONDS", "45"))
    # Reasoning tokens count against this limit, so keep it generous: a roadmap
    # that is cut off mid-JSON is useless. gpt-oss-120b allows up to 65,536.
    GROQ_MAX_COMPLETION_TOKENS: int = int(os.getenv("GROQ_MAX_COMPLETION_TOKENS", "16384"))
    GROQ_QUIZ_MAX_COMPLETION_TOKENS: int = int(os.getenv("GROQ_QUIZ_MAX_COMPLETION_TOKENS", "4096"))
    GROQ_CHAT_MAX_COMPLETION_TOKENS: int = int(os.getenv("GROQ_CHAT_MAX_COMPLETION_TOKENS", "8192"))
    GROQ_REASONING_EFFORT: str = os.getenv("GROQ_REASONING_EFFORT", "medium")
    # Roadmaps are the one-off, quality-critical call, so they think hardest.
    GROQ_ROADMAP_REASONING_EFFORT: str = os.getenv("GROQ_ROADMAP_REASONING_EFFORT", "high")

    # Hand-picked resources for core skills (dataset/curated_resources.json)
    USE_CURATED_RESOURCES: bool = os.getenv("USE_CURATED_RESOURCES", "true").lower() == "true"

    # Web Search
    TAVILY_API_KEY: str = os.getenv(
        "TAVILY_API_KEY",
        "",
    )

    # Semantic skill matching (sentence-transformer embeddings)
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL",
        "all-MiniLM-L6-v2",
    )
    EMBEDDING_MATCH_THRESHOLD: float = float(
        os.getenv(
            "EMBEDDING_MATCH_THRESHOLD",
            "0.6",
        )
    )

    # Embeddings
    EMBEDDINGS_MODEL: str = "all-MiniLM-L6-v2"

    # Prerequisite-aware path planner (app/services/path_planner.py).
    # On by default for goals without a curated curriculum. Set USE_PATH_PLANNER=false to use
    # only the possession-based topological fallback for those goals.
    USE_PATH_PLANNER: bool = os.getenv("USE_PATH_PLANNER", "true").lower() == "true"
    # LLM-first proposal followed by deterministic validation. On by default
    # for all goals; curated goals use a graph scoped to their reviewed skill
    # catalogue, while uncurated goals use the full prerequisite closure.
    # Failures fall back to the curated curriculum or existing planner path.
    USE_LLM_FIRST_VALIDATED_ROADMAP: bool = os.getenv("USE_LLM_FIRST_VALIDATED_ROADMAP", "true").lower() == "true"
    PLANNER_WEAK_THRESHOLD: float = float(os.getenv("PLANNER_WEAK_THRESHOLD", "0.50"))
    PLANNER_STRONG_THRESHOLD: float = float(os.getenv("PLANNER_STRONG_THRESHOLD", "0.85"))

    # Bayesian Knowledge Tracing. These values are fallback priors; when enough
    # labelled per-question response sequences exist, the BKT service fits a
    # regularized population-level estimate and reports its source.
    BKT_P_INITIAL: float = float(os.getenv("BKT_P_INITIAL", "0.20"))
    BKT_P_LEARN: float = float(os.getenv("BKT_P_LEARN", "0.15"))
    BKT_P_GUESS: float = float(os.getenv("BKT_P_GUESS", "0.20"))
    BKT_P_SLIP: float = float(os.getenv("BKT_P_SLIP", "0.10"))
    BKT_MIN_CALIBRATION_RESPONSES: int = int(os.getenv("BKT_MIN_CALIBRATION_RESPONSES", "100"))
    BKT_MIN_CALIBRATION_SEQUENCES: int = int(os.getenv("BKT_MIN_CALIBRATION_SEQUENCES", "10"))


    # Password reset (forgot-password feature). If SMTP_HOST is left empty,
    # the reset link is logged instead of emailed — fine for local dev.
    SMTP_HOST: str = os.getenv(
        "SMTP_HOST",
        "",
    )
    SMTP_PORT: int = int(
        os.getenv(
            "SMTP_PORT",
            "587",
        )
    )
    SMTP_USER: str = os.getenv(
        "SMTP_USER",
        "",
    )
    SMTP_PASSWORD: str = os.getenv(
        "SMTP_PASSWORD",
        "",
    )
    EMAIL_FROM: str = os.getenv(
        "EMAIL_FROM",
        "no-reply@traject.local",
    )
    FRONTEND_URL: str = os.getenv(
        "FRONTEND_URL",
        "http://localhost:5173",
    )
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30

    # Study-reminder emails. Off unless explicitly enabled AND SMTP_HOST is set.
    REMINDER_EMAILS_ENABLED: bool = os.getenv("REMINDER_EMAILS_ENABLED", "false").lower() in {"1", "true", "yes"}
    REMINDER_EMAIL_INTERVAL_SECONDS: int = int(os.getenv("REMINDER_EMAIL_INTERVAL_SECONDS", "300"))
    # Reminders that became due longer ago than this are skipped (e.g. after downtime).
    REMINDER_EMAIL_MAX_AGE_HOURS: int = int(os.getenv("REMINDER_EMAIL_MAX_AGE_HOURS", "24"))

    # AI tutor transcripts are permanently purged after this many days.
    CHAT_HISTORY_RETENTION_DAYS: int = int(os.getenv("CHAT_HISTORY_RETENTION_DAYS", "30"))
    CHAT_HISTORY_CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("CHAT_HISTORY_CLEANUP_INTERVAL_SECONDS", "86400"))
    model_config = SettingsConfigDict(
        env_file=os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.abspath(__file__)
                    )
                )
            ),
            ".env",
        ),
    )


settings = Settings()

if settings.ENVIRONMENT.lower() not in {"development", "test"} and len(settings.SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY must be set to at least 32 characters outside development.")

if settings.ENVIRONMENT.lower() not in {"development", "test"} and not settings.RATE_LIMIT_REDIS_URL:
    raise RuntimeError("RATE_LIMIT_REDIS_URL must be configured outside development so rate limits are shared across workers.")

# Ensure directories exist
os.makedirs(settings.DATASET_DIR, exist_ok=True)
os.makedirs(settings.APP_DATA_DIR, exist_ok=True)