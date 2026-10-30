"""Ratings and reports feed back into resource ranking (no network)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ResourceReport, User, UserFeedback
from app.services import resource_signals as sig
from app.services import web_search_service as ws
from app.services.web_search_service import WebSearchService

A, B, C = "https://a.test/x", "https://b.test/y", "https://c.test/z"


@pytest.fixture
def session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(sig, "SessionLocal", Session)
    db = Session()
    db.add_all([User(user_id=f"u{i}", username=f"user{i}", email=f"{i}@x.test") for i in range(5)])
    db.commit()
    yield db
    db.close()


def rate(db, url, user, stars, content_type="resource"):
    db.add(UserFeedback(feedback_id=f"{url}{user}{stars}{content_type}", user_id=user, content_id=url,
                        content_type=content_type, rating=stars))
    db.commit()


def test_no_signal_means_no_change():
    assert sig.adjustment(None) == (False, 0.0)
    assert sig.adjustment({"count": 0, "avg": None, "reports": 0}) == (False, 0.0)


def test_one_vote_barely_moves_ranking_but_three_move_it_a_lot():
    _, one = sig.adjustment({"count": 1, "avg": 5, "reports": 0})
    _, three = sig.adjustment({"count": 3, "avg": 5, "reports": 0})
    assert 0 < one < three <= sig.MAX_BONUS
    assert sig.adjustment({"count": 3, "avg": 4, "reports": 0})[1] > 0
    assert sig.adjustment({"count": 1, "avg": 1, "reports": 0})[0] is False   # one angry vote does not hide


def test_low_ratings_or_repeat_reports_hide_a_resource():
    assert sig.adjustment({"count": 3, "avg": 2.0, "reports": 0})[0] is True
    assert sig.adjustment({"count": 2, "avg": 1.0, "reports": 0})[0] is False
    assert sig.adjustment({"count": 0, "avg": None, "reports": 2})[0] is True
    assert sig.adjustment({"count": 0, "avg": None, "reports": 1})[0] is False


def test_signals_are_read_from_the_database(session):
    for u in ("u0", "u1", "u2"):
        rate(session, A, u, 5)
    rate(session, B, "u0", 1)
    rate(session, C, "u0", 5, content_type="phase")          # not a resource rating: ignored
    session.add_all([ResourceReport(user_id="u0", resource_url=C, reason="broken link"),
                     ResourceReport(user_id="u1", resource_url=C, reason="dead"),
                     ResourceReport(user_id="u1", resource_url=C, reason="again")])   # same reporter counts once
    session.commit()
    signals = sig.load_signals([A, B, C])
    assert signals[sig.normalize_url(A)] == {"count": 3, "avg": 5.0, "reports": 0}
    assert signals[sig.normalize_url(B)]["count"] == 1
    assert signals[sig.normalize_url(C)] == {"count": 0, "avg": None, "reports": 2}


def test_database_failure_falls_back_to_unadjusted_ranking(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(sig, "SessionLocal", boom)
    assert sig.load_signals([A]) == {}


def test_apply_signals_is_idempotent_and_hides(session):
    for u in ("u0", "u1", "u2"):
        rate(session, A, u, 5)
        rate(session, C, u, 1)
    signals = sig.load_signals([A, B, C])
    once = sig.apply_signals([{"url": A}, {"url": B}, {"url": C}], signals)
    assert [r["url"] for r in once] == [A, B]
    twice = sig.apply_signals(once, signals)
    assert twice[0]["community_bonus"] == once[0]["community_bonus"] > 0


def test_search_ranks_well_rated_resources_first_and_hides_reported_ones(session, monkeypatch):
    for u in ("u0", "u1", "u2"):
        rate(session, A, u, 5)
    session.add_all([ResourceReport(user_id="u0", resource_url=C, reason="x"),
                     ResourceReport(user_id="u1", resource_url=C, reason="y")])
    session.commit()

    svc = WebSearchService()
    svc.api_key, svc.youtube_api_key, svc._curated = "real-key", "", {}
    monkeypatch.setattr(ws, "filter_valid_resources", lambda items: items)

    def page(url, score):
        return {"url": url, "title": "Skill guide", "type": "article", "quality_score": score, "search_score": 0.5}

    svc._search_one = lambda skill, queries=None: [page(B, 80), page(A, 75), page(C, 99)]
    plan = [{"index": 0, "title": "P", "skills": [{"name": "Skill"}]}]
    urls = [r["url"] for r in svc.search_courses_for_plan(plan)[0]]
    assert urls == [A, B]          # A overtakes B on ratings; reported C is gone

    # A cached shortlist is re-checked against new reports on the next call.
    session.add_all([ResourceReport(user_id="u2", resource_url=A, reason="p"),
                     ResourceReport(user_id="u3", resource_url=A, reason="q")])
    session.commit()
    assert [r["url"] for r in svc.search_courses_for_plan(plan)[0]] == [B]
