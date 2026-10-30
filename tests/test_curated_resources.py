"""Curated resources: data integrity and how they merge with live search (no network)."""
import csv
import json
from pathlib import Path
from urllib.parse import urlparse

from app.services import web_search_service as ws
from app.services.link_validator import filter_relevant_resources
from app.services.web_search_service import WebSearchService, load_curated_resources
from app.utils.config import settings

DATASET = Path(__file__).resolve().parents[1] / "dataset"


def test_every_curated_skill_exists_and_every_entry_is_well_formed():
    skills = {row["skill_name"] for row in csv.DictReader(open(DATASET / "skills.csv", encoding="utf-8"))}
    data = json.loads((DATASET / "curated_resources.json").read_text(encoding="utf-8"))["skills"]
    assert len(data) >= 50
    for name, entries in data.items():
        assert name in skills, name
        assert entries, name
        urls = [e["url"] for e in entries]
        assert len(urls) == len(set(urls)), name
        for e in entries:
            assert e["title"].strip() and urlparse(e["url"]).scheme in {"http", "https"}, (name, e)
            assert e["type"] in {"documentation", "course", "tutorial", "book", "video"}, (name, e)


def test_ml_engineer_core_skills_are_covered():
    curated = load_curated_resources()
    for skill in ("MLOps", "Containerization with Docker", "CI/CD Pipelines", "Transfer Learning",
                  "Machine Learning Fundamentals", "Deep Learning", "Python Basics", "SQL for Data Science"):
        assert curated.get(skill.casefold()), skill


def test_missing_or_broken_file_is_not_fatal(tmp_path):
    assert load_curated_resources(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_curated_resources(str(bad)) == {}


def make(monkeypatch, curated):
    monkeypatch.setattr(settings, "USE_CURATED_RESOURCES", True)  # the suite turns it off by default
    svc = WebSearchService()
    svc.api_key, svc.youtube_api_key = "real-key", ""
    svc._curated = curated
    monkeypatch.setattr(ws, "filter_valid_resources", lambda items: items)
    return svc


def web(skill, n):
    return {"url": f"https://web.test/{skill}/{n}", "title": f"{skill} {n}", "type": "article",
            "quality_score": 90, "search_score": 0.9}


def test_curated_resources_lead_the_phase_and_survive_the_relevance_filter(monkeypatch):
    curated = {"mlops": [{"title": "MLOps principles", "url": "https://ml-ops.org/", "type": "tutorial"}]}
    svc = make(monkeypatch, curated)
    svc._search_one = lambda skill, queries=None: [web(skill, i) for i in range(3)]
    plan = [{"index": 0, "title": "P", "skills": [{"name": "MLOps"}, {"name": "Docker"}]}]
    shortlist = svc.search_courses_for_plan(plan)[0]
    assert shortlist[0]["url"] == "https://ml-ops.org/" and shortlist[0]["curated"] is True
    # Titles that do not repeat the skill name would normally fail the relevance check.
    odd = {**shortlist[0], "title": "Principles and practice"}
    assert filter_relevant_resources([odd], ["MLOps"], limit=3)
    assert not filter_relevant_resources([{**odd, "curated": False, "url": "https://x.test/z"}], ["MLOps"], limit=3)


def test_curated_flag_is_trusted_only_for_its_own_skill():
    resource = {"title": "Principles", "url": "https://ml-ops.org/", "curated": True, "matched_skill": "MLOps"}
    assert filter_relevant_resources([resource], ["MLOps"])
    assert not filter_relevant_resources([resource], ["Kubernetes"])


def test_curated_url_replaces_the_same_url_found_by_search(monkeypatch):
    curated = {"docker": [{"title": "Docker: Get started", "url": "https://web.test/Docker/0", "type": "documentation"}]}
    svc = make(monkeypatch, curated)
    svc._search_one = lambda skill, queries=None: [web(skill, 0)]
    out = svc.search_courses_for_plan([{"index": 0, "title": "P", "skills": [{"name": "Docker"}]}])[0]
    assert len(out) == 1 and out[0]["curated"] is True and out[0]["title"] == "Docker: Get started"


def test_switch_turns_curated_resources_off(monkeypatch):
    svc = make(monkeypatch, {"docker": [{"title": "t", "url": "https://x.test/", "type": "documentation"}]})
    assert svc._curated_for("Docker")
    monkeypatch.setattr(settings, "USE_CURATED_RESOURCES", False)
    assert svc._curated_for("Docker") == []


def test_a_video_is_kept_in_the_top_three_when_one_exists():
    doc = lambda n: {"url": f"https://d.test/{n}", "type": "documentation"}
    video = {"url": "https://www.youtube.com/watch?v=abcdefghijk", "type": "video"}
    ensure = WebSearchService._ensure_video_in_top
    crowded = [doc(1), doc(2), doc(3), doc(4), video]
    out = ensure(crowded, crowded)
    assert video in out[:3] and len(out) <= 6 and len({r["url"] for r in out}) == len(out)
    assert ensure([doc(1), video, doc(2)], [doc(1), video, doc(2)]) == [doc(1), video, doc(2)]   # already there
    docs_only = [doc(1), doc(2), doc(3)]
    assert ensure(docs_only, docs_only) == docs_only                                                  # nothing to add
    # A video that did not make the shortlist is still pulled in from the full candidate list.
    assert video in ensure([doc(1), doc(2), doc(3)], [doc(1), doc(2), doc(3), video])[:3]
