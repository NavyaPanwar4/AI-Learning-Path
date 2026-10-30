"""Phase resource search must cover every skill of a phase (no network)."""
from app.services import web_search_service as ws
from app.services.web_search_service import WebSearchService


def make(monkeypatch):
    svc = WebSearchService()
    svc.api_key, svc.youtube_api_key = "real-key", "yt-key"
    monkeypatch.setattr(ws, "filter_valid_resources", lambda items: items)
    monkeypatch.setattr(ws.settings, "WEB_SEARCH_CACHE_TTL_SECONDS", 86400)
    return svc


def res(skill, n, kind="video", score=10):
    return {"url": f"https://x.test/{skill}/{n}", "title": f"{skill} {n}", "type": kind,
            "quality_score": score - n, "search_score": 0.5}


def test_youtube_is_searched_for_every_skill_not_only_the_first(monkeypatch):
    svc = make(monkeypatch)
    searched = []
    svc._search_one = lambda skill, queries=None: []
    svc._search_youtube = lambda skill: searched.append(skill) or [res(skill, 1), res(skill, 2), res(skill, 3)]
    plan = [{"index": 0, "title": "Production ML and MLOps",
             "skills": [{"name": "MLOps"}, {"name": "Docker"}, {"name": "CI/CD"}]}]
    out = svc.search_courses_for_plan(plan)
    assert searched == ["MLOps", "Docker", "CI/CD"]
    assert {r["matched_skill"] for r in out[0]} == {"MLOps", "Docker", "CI/CD"}


def test_one_skill_cannot_crowd_out_the_others_in_the_shortlist(monkeypatch):
    svc = make(monkeypatch)
    # "Transfer Learning" has far higher scores than the other skills.
    svc._search_one = lambda skill, queries=None: [res(skill, i, "article", 100 if skill == "Transfer Learning" else 10) for i in range(4)]
    svc._search_youtube = lambda skill: []
    plan = [{"index": 0, "title": "P", "skills": [{"name": "Transfer Learning"}, {"name": "MLOps"}, {"name": "Docker"}]}]
    shortlist = svc.search_courses_for_plan(plan)[0]
    assert len(shortlist) == 6
    assert [r["matched_skill"] for r in shortlist[:3]] == ["Transfer Learning", "MLOps", "Docker"]


def test_youtube_results_are_cached_per_skill_and_failures_are_not_cached(monkeypatch):
    svc = make(monkeypatch)
    svc._search_one = lambda skill, queries=None: []
    calls = {"n": 0}

    def yt(skill):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("quota")
        return [res(skill, 1)]

    svc._search_youtube = yt
    plan = [{"index": 0, "title": "P", "skills": [{"name": "Docker"}]}]
    assert svc.search_courses_for_plan(plan)[0] == []          # failure: nothing cached
    svc._cache.pop(("phase_plan", ((0, "P", ("Docker",)),)), None)
    assert svc.search_courses_for_plan(plan)[0]                # retried and now succeeds
    svc._cache.pop(("phase_plan", ((0, "P", ("Docker",)),)), None)
    svc.search_courses_for_plan(plan)
    assert calls["n"] == 2                                     # third call served from the skill cache
