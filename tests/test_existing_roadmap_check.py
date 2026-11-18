from app.routes import roadmap_routes


def test_existing_roadmap_check_returns_false_when_goal_has_no_saved_roadmap(monkeypatch):
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "get_existing_roadmap_for_goal",
        lambda user_id, goal_id: None,
    )

    result = roadmap_routes.check_existing_roadmap("goal-1", "user-1")

    assert result == {"exists": False, "goal_id": "goal-1"}


def test_existing_roadmap_check_returns_saved_roadmap_metadata(monkeypatch):
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "get_existing_roadmap_for_goal",
        lambda user_id, goal_id: {"goal_id": goal_id, "goal_name": "Python Developer"},
    )

    result = roadmap_routes.check_existing_roadmap("goal-1", "user-1")

    assert result == {
        "exists": True,
        "goal_id": "goal-1",
        "goal_name": "Python Developer",
    }
