from app.utils.rate_limit import RequestRateLimitMiddleware


def test_quiz_routes_share_one_bucket_across_goal_and_phase():
    first = RequestRateLimitMiddleware._limit_for("/roadmap/7/phase/1/quiz")
    second = RequestRateLimitMiddleware._limit_for("/roadmap/42/phase/9/quiz/submit")
    assert first is not None and second is not None
    assert first[0] == second[0] == "quiz"
    assert first[1:] == second[1:]


def test_unrelated_path_containing_quiz_is_not_rate_limited():
    assert RequestRateLimitMiddleware._limit_for("/some/other/quiz-related-resource") is None


def test_roadmap_generation_aliases_share_a_bucket():
    sync_alias = RequestRateLimitMiddleware._limit_for("/roadmap/generate-roadmap")
    async_alias = RequestRateLimitMiddleware._limit_for("/roadmap/generate-roadmap/async")
    assert sync_alias is not None and async_alias is not None
    assert sync_alias[0] == async_alias[0] == "roadmap-generate"
