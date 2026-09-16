from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.utils.config import settings

DATABASE_URL = settings.DATABASE_URL

# check_same_thread only matters for SQLite; harmless to set unconditionally-guarded here
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency for endpoints that want an injected session.
    Existing services open/close their own short-lived sessions instead
    (mirrors the old per-call CSV read/write pattern), so this is mainly
    here for any new routes/services you add going forward.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
