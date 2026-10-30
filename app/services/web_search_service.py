import json
import os
import requests
import copy
import time
from threading import Lock
from typing import List, Dict
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.utils.config import settings
from app.utils.logger import logger
from app.services.resource_signals import apply_signals, load_signals
from app.services.link_validator import (
    filter_valid_resources,
    BLOCKED_DOMAINS,
)


CURATED_QUALITY_SCORE = 100.0


def load_curated_resources(path: str = None) -> Dict[str, List[Dict]]:
    """Return {casefolded skill name: [resource, ...]} from the curated file.

    A missing or malformed file yields an empty mapping: curated resources are
    an enhancement, never a requirement.
    """
    path = path or os.path.join(settings.DATASET_DIR, "curated_resources.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        skills = data.get("skills", {}) if isinstance(data, dict) else {}
        return {
            str(name).casefold().strip(): [
                {"title": str(r["title"]), "url": str(r["url"]), "type": str(r.get("type") or "documentation")}
                for r in entries if isinstance(r, dict) and r.get("title") and r.get("url")
            ]
            for name, entries in skills.items() if isinstance(entries, list)
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Curated resources unavailable (%s); using live search only.", exc)
        return {}


# YouTube search costs 100 quota units per call; these bound it per roadmap.
YOUTUBE_SKILLS_PER_PHASE = 3
YOUTUBE_RESULTS_PER_SKILL = 2

class WebSearchService:
    """
    Retrieves high-quality learning resources for roadmap generation.

    The important distinction here is that this service is responsible for
    finding and validating resources. The LLM should not be trusted to
    determine whether an arbitrary URL is a useful learning resource.
    """

    def __init__(self):
        self.api_key = getattr(settings, "TAVILY_API_KEY", "")
        self.base_url = "https://api.tavily.com/search"

        # Optional YouTube Data API key.
        #
        # Add YOUTUBE_API_KEY to .env if you want metadata-based YouTube
        # ranking. Without it, YouTube results are still filtered and
        # validated through Tavily + URL checks, but view/like/comment
        # ranking is unavailable.
        self.youtube_api_key = getattr(
            settings,
            "youtube_api_key",
            "",
        )
        self._cache = {}
        self._cache_lock = Lock()
        self._curated = None

    # ------------------------------------------------------------------
    # Generic web search
    # ------------------------------------------------------------------

    def _search_one(self, skill: str, queries: List[str] = None) -> List[Dict]:
        """
        Search for actual learning material for one skill.

        We deliberately avoid vague queries such as:
            "best tutorial or course to learn X"

        because those tend to surface discussions, Reddit, Q&A pages,
        listicles and low-signal content.
        """

        queries = queries or [
            f"{skill} official documentation tutorial",
            f"{skill} structured course tutorial",
            f"{skill} complete beginner to advanced tutorial",
        ]

        all_results = []
        seen_urls = set()

        for query in queries:
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": "advanced",
                "include_answer": False,
                "include_images": False,
                "include_raw_content": False,
                "exclude_domains": list(BLOCKED_DOMAINS),
                "max_results": 6,
            }

            try:
                logger.info(
                    f"Calling Tavily API to search for: {query}"
                )

                response = requests.post(
                    self.base_url,
                    json=payload,
                    timeout=20,
                )

                if response.status_code != 200:
                    logger.error(
                        f"Tavily API error: "
                        f"{response.status_code} - {response.text}"
                    )
                    continue

                results = response.json().get(
                    "results",
                    [],
                )

                for result in results:
                    url = result.get("url", "")

                    if not url or url in seen_urls:
                        continue

                    seen_urls.add(url)

                    all_results.append(
                        {
                            "title": result.get(
                                "title",
                                "",
                            ),
                            "url": url,
                            "type": self._classify_resource(
                                url,
                                result.get("title", ""),
                            ),
                            "content": result.get(
                                "content",
                                "",
                            ),
                            # This is the query/topic that produced the result,
                            # not proof of topical relevance. The relevance
                            # validator deliberately checks title/content/URL.
                            "skill": skill,
                            "source": self._get_domain(url),
                            "search_score": result.get("score", 0),
                            "quality_score": self._base_quality_score(
                                url,
                                result.get("title", ""),
                            ),
                        }
                    )

            except requests.exceptions.RequestException as exc:
                logger.error(
                    f"Tavily API connection error: {exc}"
                )

        return all_results

    # ------------------------------------------------------------------
    # YouTube
    # ------------------------------------------------------------------

    def _search_youtube(self, skill: str) -> List[Dict]:
        """
        Search YouTube specifically.

        If a YouTube Data API key is available, use the API to retrieve
        statistics and video status. This lets us reject unavailable
        videos and rank videos using views, likes and comments.

        If no API key exists, return [] rather than pretending we can
        reliably measure YouTube quality.
        """

        if not self.youtube_api_key:
            logger.info(
                "YOUTUBE_API_KEY is not configured; "
                "skipping metadata-based YouTube search."
            )
            return []

        search_url = (
            "https://www.googleapis.com/youtube/v3/search"
        )

        params = {
            "part": "snippet",
            "q": f"{skill} tutorial",
            "type": "video",
            "maxResults": 10,
            "order": "relevance",
            "videoEmbeddable": "true",
            "key": self.youtube_api_key,
        }

        try:
            response = requests.get(
                search_url,
                params=params,
                timeout=15,
            )

            if response.status_code != 200:
                logger.error(
                    f"YouTube search API error: "
                    f"{response.status_code} - {response.text}"
                )
                return []

            items = response.json().get(
                "items",
                [],
            )

            video_ids = [
                item.get("id", {}).get("videoId")
                for item in items
                if item.get("id", {}).get("videoId")
            ]

            if not video_ids:
                return []

            videos = self._get_youtube_video_details(
                video_ids
            )

            resources = []

            for video in videos:
                video_id = video.get("id")

                snippet = video.get(
                    "snippet",
                    {},
                )

                status = video.get(
                    "status",
                    {},
                )

                statistics = video.get(
                    "statistics",
                    {},
                )

                # Explicit availability checks.
                if status.get("privacyStatus") != "public":
                    continue

                if status.get("embeddable") is False:
                    continue

                title = snippet.get(
                    "title",
                    "",
                )

                channel = snippet.get(
                    "channelTitle",
                    "",
                )

                views = int(
                    statistics.get(
                        "viewCount",
                        0,
                    )
                    or 0
                )

                likes = int(
                    statistics.get(
                        "likeCount",
                        0,
                    )
                    or 0
                )

                comments = int(
                    statistics.get(
                        "commentCount",
                        0,
                    )
                    or 0
                )

                quality_score = self._youtube_quality_score(
                    views,
                    likes,
                    comments,
                )

                resources.append(
                    {
                        "title": title,
                        "url": (
                            f"https://www.youtube.com/watch?v="
                            f"{video_id}"
                        ),
                        "type": "video",
                        "content": (
                            f"YouTube tutorial by {channel}. "
                            f"Views: {views}. "
                            f"Likes: {likes}. "
                            f"Comments: {comments}."
                        ),
                        "skill": skill,
                        "source": "youtube.com",
                        "channel": channel,
                        "views": views,
                        "likes": likes,
                        "comments": comments,
                        "quality_score": quality_score,
                        "verified_available": True,
                    }
                )

            resources.sort(
                key=lambda resource: resource.get(
                    "quality_score",
                    0,
                ),
                reverse=True,
            )

            # Don't overwhelm the roadmap.
            return resources[:3]

        except requests.exceptions.RequestException as exc:
            logger.error(
                f"YouTube API connection error: {exc}"
            )
            return []

    def _get_youtube_video_details(
        self,
        video_ids: List[str],
    ) -> List[Dict]:
        url = (
            "https://www.googleapis.com/youtube/v3/videos"
        )

        params = {
            "part": "snippet,statistics,status,contentDetails",
            "id": ",".join(video_ids),
            "key": self.youtube_api_key,
        }

        try:
            response = requests.get(
                url,
                params=params,
                timeout=15,
            )

            if response.status_code != 200:
                logger.error(
                    f"YouTube video details API error: "
                    f"{response.status_code}"
                )
                return []

            return response.json().get(
                "items",
                [],
            )

        except requests.exceptions.RequestException as exc:
            logger.error(
                f"YouTube details API connection error: {exc}"
            )
            return []

    # ------------------------------------------------------------------
    # Resource classification / scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _get_domain(url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    @staticmethod
    def _classify_resource(
        url: str,
        title: str,
    ) -> str:
        domain = WebSearchService._get_domain(url)
        lower_url = url.lower()
        lower_title = title.lower()

        if (
            "youtube.com" in domain
            or "youtu.be" in domain
        ):
            return "video"

        if (
            "docs." in domain
            or "/docs/" in lower_url
            or "documentation" in lower_title
        ):
            return "documentation"

        if (
            "course" in lower_url
            or "course" in lower_title
            or "udemy" in domain
            or "coursera" in domain
            or "edx.org" in domain
            or "freecodecamp.org" in domain
        ):
            return "course"

        if (
            "tutorial" in lower_url
            or "tutorial" in lower_title
        ):
            return "tutorial"

        return "article"

    @staticmethod
    def _base_quality_score(
        url: str,
        title: str,
    ) -> float:
        """
        Heuristic score for non-YouTube resources.

        This is intentionally conservative. We reward known educational
        domains and penalize pages that look like discussions/questions.
        """

        domain = WebSearchService._get_domain(url)

        lower_url = url.lower()
        lower_title = title.lower()

        score = 50.0

        high_quality_domains = {
            "developer.mozilla.org": 30,
            "docs.python.org": 30,
            "react.dev": 30,
            "nextjs.org": 30,
            "pytorch.org": 30,
            "tensorflow.org": 30,
            "scikit-learn.org": 30,
            "numpy.org": 25,
            "pandas.pydata.org": 25,
            "learn.microsoft.com": 25,
            "developer.android.com": 25,
            "aws.amazon.com": 20,
            "cloud.google.com": 20,
            "coursera.org": 20,
            "edx.org": 20,
            "freecodecamp.org": 20,
            "geeksforgeeks.org": 10,
        }

        score += high_quality_domains.get(
            domain,
            0,
        )

        bad_signals = [
            "reddit",
            "stackoverflow.com/questions",
            "quora",
            "forum",
            "discussion",
            "thread",
            "question",
            "questions",
            "community",
        ]

        for signal in bad_signals:
            if signal in lower_url or signal in lower_title:
                score -= 80

        educational_signals = [
            "tutorial",
            "documentation",
            "guide",
            "course",
            "learn",
            "lesson",
            "reference",
            "getting started",
            "introduction",
        ]

        for signal in educational_signals:
            if signal in lower_url or signal in lower_title:
                score += 5

        return score

    @staticmethod
    def _youtube_quality_score(
        views: int,
        likes: int,
        comments: int,
    ) -> float:
        """
        Combine popularity signals without letting raw view count
        completely dominate.

        Log scaling prevents a huge channel from automatically winning
        simply because it has more subscribers.
        """

        import math

        view_score = math.log10(
            max(views, 1)
        ) * 8

        like_score = math.log10(
            max(likes, 1)
        ) * 12

        comment_score = math.log10(
            max(comments, 1)
        ) * 6

        engagement_ratio = (
            likes / max(views, 1)
        )

        engagement_score = min(
            engagement_ratio * 1000,
            20,
        )

        return (
            view_score
            + like_score
            + comment_score
            + engagement_score
        )

    # ------------------------------------------------------------------
    # Phase-scoped resource retrieval for roadmap generation
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_community_signals(by_phase: Dict[int, List[Dict]]) -> Dict[int, List[Dict]]:
        """Re-check a cached shortlist against the latest ratings and reports."""
        urls = {r["url"] for items in by_phase.values() for r in items if r.get("url")}
        signals = load_signals(urls) if urls else {}
        if not signals:
            return by_phase
        result = {}
        for idx, items in by_phase.items():
            adjusted = apply_signals(items, signals)
            adjusted.sort(key=lambda r: (bool(r.get("curated")), WebSearchService._candidate_rank(r)), reverse=True)
            result[idx] = adjusted
        return result

    @staticmethod
    def _is_video(resource: Dict) -> bool:
        url = str(resource.get("url") or "").lower()
        return str(resource.get("type") or "").lower() == "video" or "youtube.com/watch" in url or "youtu.be/" in url

    @classmethod
    def _ensure_video_in_top(cls, shortlist: List[Dict], candidates: List[Dict], top: int = 3, size: int = 6) -> List[Dict]:
        """Keep one video among the first top resources when any exists.

        Curated docs and courses outrank videos, and the final selection takes
        the first few that pass the relevance check, so without this a phase
        could end up with no video at all.
        """
        if any(cls._is_video(r) for r in shortlist[:top]):
            return shortlist
        video = next((r for r in shortlist[top:] if cls._is_video(r)), None)             or next((r for r in candidates if cls._is_video(r) and r not in shortlist), None)
        if video is None:
            return shortlist
        rest = [r for r in shortlist if r is not video]
        position = min(top - 1, len(rest))
        return (rest[:position] + [video] + rest[position:])[:size]

    def _curated_for(self, skill: str) -> List[Dict]:
        if not getattr(settings, "USE_CURATED_RESOURCES", True):
            return []
        if self._curated is None:
            self._curated = load_curated_resources()
        return self._curated.get(skill.casefold().strip(), [])

    @staticmethod
    def _skill_name(raw_skill) -> str:
        if isinstance(raw_skill, dict):
            return str(raw_skill.get("name") or raw_skill.get("skill_name") or "").strip()
        return str(raw_skill or "").strip()

    @staticmethod
    def _candidate_rank(resource: Dict) -> float:
        try:
            search_score = float(resource.get("search_score") or 0.0)
        except (TypeError, ValueError):
            search_score = 0.0
        try:
            quality_score = float(resource.get("quality_score") or 0.0)
        except (TypeError, ValueError):
            quality_score = 0.0
        try:
            community_bonus = float(resource.get("community_bonus") or 0.0)
        except (TypeError, ValueError):
            community_bonus = 0.0
        return quality_score + 20.0 * search_score + community_bonus

    def search_courses_for_plan(self, plan_phases: List[Dict]) -> Dict[int, List[Dict]]:
        """Find resources for every phase, rather than pooling the first 8 skills.

        Each distinct skill gets one focused web query. Candidates retain their
        phase association and are URL-validated once. The caller must still run
        topical relevance checks against each phase before exposing the links.
        """
        phase_specs = []
        for position, phase in enumerate(plan_phases or []):
            if not isinstance(phase, dict):
                continue
            try:
                phase_index = int(phase.get("index", position))
            except (TypeError, ValueError):
                phase_index = position
            phase_title = str(phase.get("title") or f"Phase {phase_index + 1}")
            skills = list(dict.fromkeys(
                name for name in (self._skill_name(item) for item in phase.get("skills", [])) if name
            ))
            phase_specs.append((phase_index, phase_title, skills))

        empty_result = {phase_index: [] for phase_index, _, _ in phase_specs}
        if not self.api_key or self.api_key.strip().casefold() in {
            "your_tavily_api_key", "replace_me", "changeme", "your_api_key"
        }:
            logger.warning(
                "Tavily resource search is not configured; roadmap phases will "
                "not receive unverified LLM-generated resource URLs. Set a real TAVILY_API_KEY in .env."
            )
            return empty_result

        signature = tuple((idx, title, tuple(skills)) for idx, title, skills in phase_specs)
        cache_key = ("phase_plan", signature)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < settings.WEB_SEARCH_CACHE_TTL_SECONDS:
                return self._apply_community_signals(copy.deepcopy(cached[1]))

        skill_results: Dict[str, List[Dict]] = {}
        per_phase: Dict[int, Dict[str, Dict]] = {idx: {} for idx, _, _ in phase_specs}

        for phase_index, phase_title, skills in phase_specs:
            for skill in skills:
                skill_key = skill.casefold().strip()
                if skill_key not in skill_results:
                    individual_cache_key = ("phase_skill", skill_key)
                    with self._cache_lock:
                        cached_skill = self._cache.get(individual_cache_key)
                    if cached_skill and time.monotonic() - cached_skill[0] < settings.WEB_SEARCH_CACHE_TTL_SECONDS:
                        results = copy.deepcopy(cached_skill[1])
                    else:
                        # One focused query per skill lets later phases get
                        # coverage without increasing total query volume versus
                        # the old 3-queries-for-first-8-skills strategy.
                        query = f"{skill} official documentation tutorial course"
                        results = self._search_one(skill, queries=[query])[:4]
                        with self._cache_lock:
                            self._cache[individual_cache_key] = (
                                time.monotonic(), copy.deepcopy(results)
                            )
                    skill_results[skill_key] = results

                for result in skill_results[skill_key]:
                    url = str(result.get("url") or "").strip()
                    if not url:
                        continue
                    candidate = copy.deepcopy(result)
                    candidate["phase_index"] = phase_index
                    candidate["phase_title"] = phase_title
                    candidate["matched_skill"] = skill
                    existing = per_phase[phase_index].get(url)
                    if existing is None or self._candidate_rank(candidate) > self._candidate_rank(existing):
                        per_phase[phase_index][url] = candidate

                # Hand-picked resources win over anything the web search found
                # for the same URL, and sort ahead of it (see the shortlist).
                for entry in self._curated_for(skill):
                    per_phase[phase_index][entry["url"]] = {
                        **entry,
                        "content": "",
                        "quality_score": CURATED_QUALITY_SCORE,
                        "search_score": 1.0,
                        "curated": True,
                        "phase_index": phase_index,
                        "phase_title": phase_title,
                        "matched_skill": skill,
                    }

            # YouTube: search each of the phase's skills (not only the first),
            # so a phase led by one skill cannot be filled with videos about
            # it. Results are cached per skill, so each skill costs YouTube
            # quota at most once per cache window.
            if skills and self.youtube_api_key:
                for skill in skills[:YOUTUBE_SKILLS_PER_PHASE]:
                    skill_key = skill.casefold().strip()
                    yt_cache_key = ("phase_youtube", skill_key)
                    with self._cache_lock:
                        cached_yt = self._cache.get(yt_cache_key)
                    if cached_yt and time.monotonic() - cached_yt[0] < settings.WEB_SEARCH_CACHE_TTL_SECONDS:
                        youtube_results = copy.deepcopy(cached_yt[1])
                    else:
                        try:
                            youtube_results = self._search_youtube(skill)[:YOUTUBE_RESULTS_PER_SKILL]
                        except Exception as exc:
                            logger.warning(
                                "YouTube resource search failed for phase %s skill %r: %s",
                                phase_index, skill, exc,
                            )
                            continue  # do not cache a failure
                        with self._cache_lock:
                            self._cache[yt_cache_key] = (time.monotonic(), copy.deepcopy(youtube_results))
                    for result in youtube_results:
                        url = str(result.get("url") or "").strip()
                        if not url:
                            continue
                        candidate = copy.deepcopy(result)
                        candidate["phase_index"] = phase_index
                        candidate["phase_title"] = phase_title
                        candidate["matched_skill"] = skill
                        existing = per_phase[phase_index].get(url)
                        if existing is None or self._candidate_rank(candidate) > self._candidate_rank(existing):
                            per_phase[phase_index][url] = candidate

        # Check each unique URL only once, while preserving the candidate's
        # phase-specific association for later topical matching.
        unique_urls: Dict[str, Dict] = {}
        for resources in per_phase.values():
            for url, resource in resources.items():
                existing = unique_urls.get(url)
                if existing is None or self._candidate_rank(resource) > self._candidate_rank(existing):
                    unique_urls[url] = resource

        valid_urls = {
            str(resource.get("url"))
            for resource in filter_valid_resources(list(unique_urls.values()))
            if resource.get("url")
        }

        # Learner ratings and reports: hide resources people flagged, nudge the
        # ranking toward ones they rated well.
        signals = load_signals(valid_urls)

        result_by_phase: Dict[int, List[Dict]] = {}
        for phase_index, _, _ in phase_specs:
            candidates = [
                resource for url, resource in per_phase.get(phase_index, {}).items()
                if url in valid_urls
            ]
            candidates = apply_signals(candidates, signals)
            candidates.sort(key=lambda r: (bool(r.get("curated")), self._candidate_rank(r)), reverse=True)
            # Take the best candidate of each skill first (round-robin), so no
            # single skill can crowd the others out of the shortlist. The
            # relevance validator makes the final selection from these six.
            by_skill: Dict[str, List[Dict]] = {}
            for resource in candidates:
                by_skill.setdefault(str(resource.get("matched_skill") or ""), []).append(resource)
            shortlist: List[Dict] = []
            while len(shortlist) < 6 and any(by_skill.values()):
                for group in by_skill.values():
                    if group and len(shortlist) < 6:
                        shortlist.append(group.pop(0))
            result_by_phase[phase_index] = self._ensure_video_in_top(shortlist, candidates)

        with self._cache_lock:
            self._cache[cache_key] = (time.monotonic(), copy.deepcopy(result_by_phase))
        logger.info(
            "Phase-scoped resource search complete: phases=%d queried_skills=%d validated_urls=%d",
            len(phase_specs), len(skill_results), len(valid_urls),
        )
        return result_by_phase

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_courses(
        self,
        missing_skills: List[str],
    ) -> List[Dict]:

        if not self.api_key:
            logger.info(
                "TAVILY_API_KEY is not configured; "
                "skipping optional live web search."
            )
            return []

        if not missing_skills:
            return []

        cache_key = tuple(sorted({skill.strip().lower() for skill in missing_skills if skill and skill.strip()}))
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < settings.WEB_SEARCH_CACHE_TTL_SECONDS:
                return copy.deepcopy(cached[1])

        seen_urls = set()
        combined: List[Dict] = []

        # Search every missing skill rather than only the first three.
        #
        # Cap at 8 to avoid an excessive number of external API calls.
        for skill in missing_skills[:8]:

            web_results = self._search_one(skill)

            for resource in web_results:
                url = resource.get("url", "")

                if url and url not in seen_urls:
                    seen_urls.add(url)
                    combined.append(resource)

            # YouTube is handled separately because it has its own
            # availability + statistics API.
            youtube_results = self._search_youtube(skill)

            for resource in youtube_results:
                url = resource.get("url", "")

                if url and url not in seen_urls:
                    seen_urls.add(url)
                    combined.append(resource)

        if not combined:
            return []

        # Validate generic URLs.
        #
        # YouTube API results have already passed explicit YouTube
        # availability checks, but running the normal URL validation as
        # well provides an additional safety layer.
        validated = filter_valid_resources(
            combined
        )

        # Sort all resources by quality.
        validated.sort(
            key=lambda resource: resource.get(
                "quality_score",
                0,
            ),
            reverse=True,
        )

        # Keep a useful amount of context for the LLM.
        #
        # We don't want hundreds of URLs in the prompt.
        result = validated[:20]
        with self._cache_lock:
            self._cache[cache_key] = (time.monotonic(), copy.deepcopy(result))
        return result


web_search_service = WebSearchService()