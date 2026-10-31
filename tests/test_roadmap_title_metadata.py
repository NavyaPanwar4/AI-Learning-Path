from app.models.schemas import RoadmapResponse


def test_roadmap_response_preserves_human_readable_goal_name():
    payload = {
        "goal_id": "goal-123",
        "goal_name": "Full Stack Developer",
        "phases": [],
    }

    response = RoadmapResponse.model_validate(payload)

    assert response.goal_id == "goal-123"
    assert response.goal_name == "Full Stack Developer"
    assert response.model_dump()["goal_name"] == "Full Stack Developer"


def test_roadmap_response_allows_older_payload_without_goal_name():
    response = RoadmapResponse.model_validate({"goal_id": "goal-legacy", "phases": []})

    assert response.goal_name is None
