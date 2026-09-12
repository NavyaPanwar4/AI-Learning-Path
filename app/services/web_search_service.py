import requests
from typing import List, Dict, Any
from app.utils.config import settings
from app.utils.logger import logger

class WebSearchService:
    def __init__(self):
        self.api_key = getattr(settings, "TAVILY_API_KEY", "")
        self.base_url = "https://api.tavily.com/search"

    def search_courses(self, missing_skills: List[str]) -> List[Dict[str, str]]:
        if not self.api_key:
            logger.info("TAVILY_API_KEY is not configured; skipping optional live web search.")
            return []
            
        if not missing_skills:
            return []

        query = f"best current online courses, tutorials, and YouTube videos to learn {' and '.join(missing_skills)}"
        
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "max_results": 5,
        }
        
        try:
            logger.info(f"Calling Tavily API to search for: {query}")
            response = requests.post(self.base_url, json=payload, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                
                mapped_results = []
                for res in results:
                    mapped_results.append({
                        "title": res.get("title", ""),
                        "url": res.get("url", ""),
                        "type": "web_article_or_video",
                        "content": res.get("content", "")
                    })
                return mapped_results
            else:
                logger.error(f"Tavily API error: {response.status_code} - {response.text}")
                return []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Tavily API connection error: {e}")
            return []
            
web_search_service = WebSearchService()
