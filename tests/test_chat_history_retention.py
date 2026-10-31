from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ChatMessage
import app.services.chat_history_retention_service as retention_service
import app.services.chat_service as chat_service_module


@pytest.fixture
def isolated_chat_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(retention_service, "SessionLocal", test_session_local)
    monkeypatch.setattr(chat_service_module, "SessionLocal", test_session_local)
    yield test_session_local
    engine.dispose()


def test_retention_cleanup_deletes_only_messages_older_than_30_days(isolated_chat_db, monkeypatch):
    monkeypatch.setattr(retention_service.settings, "CHAT_HISTORY_RETENTION_DAYS", 30)
    now = datetime(2026, 10, 31, 12, 0, 0)
    db = isolated_chat_db()
    try:
        db.add_all(
            [
                ChatMessage(
                    user_id="user-1",
                    goal_id="goal-1",
                    role="user",
                    content="expired",
                    created_at=now - timedelta(days=31),
                ),
                ChatMessage(
                    user_id="user-1",
                    goal_id="goal-1",
                    role="assistant",
                    content="recent",
                    created_at=now - timedelta(days=29),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    deleted = retention_service.purge_expired_chat_history(now=now)

    db = isolated_chat_db()
    try:
        remaining = db.query(ChatMessage).all()
        assert deleted == 1
        assert len(remaining) == 1
        assert remaining[0].content == "recent"
    finally:
        db.close()


def test_clear_history_deletes_only_the_authenticated_users_messages(isolated_chat_db):
    db = isolated_chat_db()
    try:
        db.add_all(
            [
                ChatMessage(
                    user_id="user-1", goal_id="goal-1", role="user", content="my question"
                ),
                ChatMessage(
                    user_id="user-1", goal_id="goal-1", role="assistant", content="my answer"
                ),
                ChatMessage(
                    user_id="user-2",
                    goal_id="goal-1",
                    role="user",
                    content="another user's question",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    result = chat_service_module.ChatService().clear_history("user-1")

    db = isolated_chat_db()
    try:
        remaining = db.query(ChatMessage).all()
        assert result["deleted_count"] == 2
        assert len(remaining) == 1
        assert remaining[0].user_id == "user-2"
    finally:
        db.close()
