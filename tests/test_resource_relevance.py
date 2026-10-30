"""Regression tests for phase-specific resource search and relevance filtering."""

from app.services.link_validator import filter_relevant_resources
from app.services.web_search_service import WebSearchService


def test_general_machine_learning_resource_is_not_accepted_for_deep_learning():
    resource = {
        "title": "Machine Learning for Everybody – Full Course",
        "url": "https://example.org/machine-learning-intro",
        "type": "video",
        # This field is the search query that returned the result, not proof.
        "skill": "Deep Learning",
        "content": "A broad introduction to general machine learning concepts.",
    }

    assert filter_relevant_resources([resource], ["Deep Learning"]) == []


def test_general_machine_learning_resource_is_not_accepted_for_transfer_learning():
    resource = {
        "title": "Machine Learning for Everybody – Full Course",
        "url": "https://example.org/machine-learning-intro",
        "type": "video",
        "skill": "Transfer Learning",
        "content": "A general overview of supervised learning and models.",
    }

    assert filter_relevant_resources([resource], ["Transfer Learning"]) == []


def test_specific_transfer_learning_resource_is_accepted():
    resource = {
        "title": "Transfer Learning with Pretrained Neural Networks",
        "url": "https://example.org/transfer-learning",
        "type": "article",
        "content": "Fine-tuning a pretrained model for a new task.",
    }

    result = filter_relevant_resources([resource], ["Transfer Learning"])

    assert len(result) == 1
    assert result[0]["url"] == resource["url"]


def test_wrong_search_skill_tag_does_not_make_resource_relevant():
    resource = {
        "title": "Pandas for Exploratory Data Analysis",
        "url": "https://example.org/pandas-eda",
        "type": "video",
        "skill": "MLOps",
        "content": "Working with DataFrames and plotting distributions.",
    }

    assert filter_relevant_resources([resource], ["MLOps"]) == []


def test_relevant_pandas_resource_is_accepted_for_data_wrangling():
    resource = {
        "title": "Complete Python Pandas Data Science Tutorial",
        "url": "https://example.org/pandas",
        "type": "video",
        "content": "Read CSV files, clean data, and transform DataFrames with pandas.",
    }

    result = filter_relevant_resources([resource], ["Data Wrangling with Pandas"])

    assert len(result) == 1
    assert result[0]["title"] == resource["title"]


def test_verified_result_title_overrides_llm_supplied_title_for_matching():
    llm_resource = {
        "title": "A Deep Learning Course",
        "url": "https://example.org/verified-url",
        "type": "video",
    }
    verified_resource = {
        "title": "Machine Learning for Everybody",
        "url": "https://example.org/verified-url",
        "type": "video",
        "content": "General machine learning introduction.",
        "skill": "Deep Learning",
    }

    assert filter_relevant_resources(
        [llm_resource],
        ["Deep Learning"],
        verified_resources=[verified_resource],
    ) == []


def test_phase_search_covers_skills_beyond_first_eight(monkeypatch):
    service = WebSearchService()
    service.api_key = "test-tavily-key"
    # Keep this test hermetic even when the developer's .env contains a real
    # YOUTUBE_API_KEY. The test is asserting coverage from _search_one only.
    service.youtube_api_key = ""
    monkeypatch.setattr(service, "_search_youtube", lambda skill: [])
    queried = []

    def fake_search_one(skill, queries=None):
        queried.append(skill)
        slug = skill.lower().replace(" ", "-")
        return [{
            "title": f"Official tutorial for {skill}",
            "url": f"https://example.org/{slug}",
            "type": "article",
            "content": f"Learn {skill} using an official tutorial.",
            "skill": skill,
            "source": "example.org",
            "quality_score": 50,
            "search_score": 0.9,
        }]

    monkeypatch.setattr(service, "_search_one", fake_search_one)
    monkeypatch.setattr(
        "app.services.web_search_service.filter_valid_resources",
        lambda resources, max_workers=8: resources,
    )

    plan = [
        {
            "index": 0,
            "title": "Foundations",
            "skills": [{"name": f"Foundation Skill {i}"} for i in range(1, 9)],
        },
        {
            "index": 1,
            "title": "Production ML",
            "skills": [
                {"name": "Transfer Learning"},
                {"name": "MLOps"},
                {"name": "Containerization with Docker"},
                {"name": "CI/CD Pipelines"},
            ],
        },
    ]

    result = service.search_courses_for_plan(plan)

    assert len(queried) == 12
    assert "Transfer Learning" in queried
    assert "MLOps" in queried
    assert set(result) == {0, 1}
    assert all(item["phase_index"] == 1 for item in result[1])
    assert len(result[1]) == 4


def test_plan_prompt_scopes_verified_resources_to_phase_index():
    from app.services.llm_service import LLMService

    plan = [
        {"index": 0, "title": "Pandas", "skills": [{"id": "1", "name": "Data Wrangling with Pandas", "action": "learn"}]},
        {"index": 1, "title": "MLOps", "skills": [{"id": "2", "name": "MLOps", "action": "learn"}]},
    ]
    resources = {
        "0": [{"title": "Pandas documentation", "url": "https://example.org/pandas", "type": "documentation"}],
        "1": [],
    }

    prompt = LLMService.build_plan_elaboration_prompt(
        plan,
        goal_name="ML Engineer Path",
        resources=resources,
    )

    assert "VERIFIED RESOURCES BY PHASE INDEX" in prompt
    assert "never borrow a URL from another phase" in prompt
    assert '"1": []' in prompt
