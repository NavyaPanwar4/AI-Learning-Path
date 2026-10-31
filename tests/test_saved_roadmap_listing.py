"""Regression tests for filtering the internal LLM-first Algorithms test path."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import Roadmap, User
from app.services import roadmap_service as roadmap_service_module


@pytest.fixture
def roadmap_listing_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(roadmap_service_module, "SessionLocal", Session)

    db = Session()
    db.add_all([
        User(user_id="listing-user", username="listing-user", email="listing@example.test"),
        User(user_id="other-user", username="other-user", email="other@example.test"),
    ])
    db.flush()
    db.add_all([
        Roadmap(
            user_id="listing-user",
            goal_id="test-llm-roadmap",
            goal_name="test llm-first-roadmap algorithms learning path",
            data="{}",
            is_complete=False,
        ),
        Roadmap(
            user_id="listing-user",
            goal_id="master-algorithms",
            goal_name="Master Algorithms",
            data="{}",
            is_complete=False,
        ),
        Roadmap(
            user_id="listing-user",
            goal_id="ml-engineer",
            goal_name="Machine Learning Engineer",
            data="{}",
            is_complete=True,
        ),
        Roadmap(
            user_id="other-user",
            goal_id="other-test",
            goal_name="test llm-first-roadmap algorithms learning path",
            data="{}",
            is_complete=False,
        ),
    ])
    db.commit()
    db.close()

    try:
        yield
    finally:
        db = Session()
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_saved_roadmaps_listing_hides_only_internal_test_path(roadmap_listing_db):
    result = roadmap_service_module.roadmap_service.get_saved_roadmaps("listing-user")

    assert {item["goal_id"] for item in result} == {"master-algorithms", "ml-engineer"}
    assert all("test llm-first-roadmap algorithms learning path" not in item["goal_name"].casefold() for item in result)


def test_test_path_name_matching_ignores_case_and_punctuation():
    assert roadmap_service_module._is_hidden_test_roadmap_name(
        "TEST LLM-FIRST-ROADMAP: Algorithms Learning Path"
    )
    assert not roadmap_service_module._is_hidden_test_roadmap_name("Master Algorithms")
