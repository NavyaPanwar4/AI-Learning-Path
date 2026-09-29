import requests
from typing import List, Dict
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.utils.config import settings
from app.utils.logger import logger
from app.services.link_validator import (
    filter_valid_resources,
    BLOCKED_DOMAINS,
)


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

    # ------------------------------------------------------------------
    # Generic web search
    # ------------------------------------------------------------------

    def _search_one(self, skill: str) -> List[Dict]:
        """
        Search for actual learning material for one skill.

        We deliberately avoid vague queries such as:
            "best tutorial or course to learn X"

        because those tend to surface discussions, Reddit, Q&A pages,
        listicles and low-signal content.
        """

        queries = [
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
                            "skill": skill,
                            "source": self._get_domain(url),
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
        return validated[:20]


web_search_service = WebSearchService()