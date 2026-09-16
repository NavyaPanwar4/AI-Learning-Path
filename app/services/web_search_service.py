import requests
from typing import List, Dict
from app.utils.config import settings
from app.utils.logger import logger
from app.services.link_validator import filter_valid_resources, BLOCKED_DOMAINS


class WebSearchService:
    def __init__(self):
        self.api_key = getattr(settings, "TAVILY_API_KEY", "")
        self.base_url = "https://api.tavily.com/search"

    def _search_one(self, skill: str) -> List[Dict[str, str]]:
        query = f"best tutorial or course to learn {skill} for beginners"

        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",  # slower but meaningfully more relevant than "basic"
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "exclude_domains": list(BLOCKED_DOMAINS),
            "max_results": 5,
        }

        try:
            logger.info(f"Calling Tavily API to search for: {query}")
            response = requests.post(self.base_url, json=payload, timeout=20)
            if response.status_code == 200:
                results = response.json().get("results", [])
                return [
                    {
                        "title": res.get("title", ""),
                        "url": res.get("url", ""),
                        "type": "web_article_or_video",
                        "content": res.get("content", ""),
                        "skill": skill,  # which missing skill this was searched for — lets the
                        # LLM place it in the right phase instead of reusing it everywhere
                    }
                    for res in results
                ]
            logger.error(f"Tavily API error: {response.status_code} - {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Tavily API connection error: {e}")
        return []

    def search_courses(self, missing_skills: List[str]) -> List[Dict[str, str]]:
        if not self.api_key:
            logger.info("TAVILY_API_KEY is not configured; skipping optional live web search.")
            return []

        if not missing_skills:
            return []

        # One targeted query per skill beats one vague combined query — a
        # generic "learn X and Y" search is exactly what surfaces forum
        # threads and random videos instead of an actual course/doc page.
        # Capped to the top 3 missing skills to bound API calls + latency.
        seen_urls = set()
        combined: List[Dict[str, str]] = []
        for skill in missing_skills[:3]:
            for res in self._search_one(skill):
                if res["url"] and res["url"] not in seen_urls:
                    seen_urls.add(res["url"])
                    combined.append(res)

        # Tavily indexes pages that can have since gone down or moved, and
        # exclude_domains isn't a 100% guarantee — validate + re-filter here.
        validated = filter_valid_resources(combined)
        return validated[:8]


web_search_service = WebSearchService()