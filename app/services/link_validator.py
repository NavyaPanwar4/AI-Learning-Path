"""Checks that a resource URL actually resolves — and isn't a forum/social
post — before it reaches the user.

Used to catch three separate sources of bad links: stale results from the
live web search, low-signal domains (reddit, random video hosts, etc.) that
happen to rank for a vague query, and URLs an LLM invented despite being
told not to.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List
from urllib.parse import urlparse

import requests

from app.utils.logger import logger

_TIMEOUT_SECONDS = 6
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LearningPathBot/1.0)"}

# Domains that are usually reachable but rarely a *good* learning resource —
# forums, social feeds, and UGC sites where relevance to the query is
# coincidental rather than curated. Extend this list as you spot more.
BLOCKED_DOMAINS = {
    "reddit.com", "www.reddit.com", "old.reddit.com",
    "quora.com", "www.quora.com",
    "pinterest.com", "www.pinterest.com",
    "tiktok.com", "www.tiktok.com",
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "twitter.com", "x.com", "www.twitter.com", "www.x.com",
    "instagram.com", "www.instagram.com",
}


def _is_blocked_domain(url: str) -> bool:
    try:
        return urlparse(url).netloc.lower() in BLOCKED_DOMAINS
    except Exception:
        return False


def _is_reachable(url: str) -> bool:
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False
    if _is_blocked_domain(url):
        return False
    try:
        resp = requests.head(url, allow_redirects=True, timeout=_TIMEOUT_SECONDS, headers=_HEADERS)
        if resp.status_code < 400:
            return True
        resp = requests.get(
            url, allow_redirects=True, timeout=_TIMEOUT_SECONDS, headers=_HEADERS, stream=True
        )
        return resp.status_code < 400
    except requests.exceptions.RequestException:
        return False


def filter_valid_resources(resources: List[Dict], max_workers: int = 8) -> List[Dict]:
    """Return only the resources whose URL actually resolves right now and
    isn't on the low-signal domain blocklist."""
    if not resources:
        return []

    valid = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(_is_reachable, r.get("url", "")): r for r in resources}
        for future in as_completed(future_map):
            r = future_map[future]
            try:
                if future.result():
                    valid.append(r)
                else:
                    logger.info(f"Dropping dead/low-quality resource link: {r.get('url')}")
            except Exception as exc:
                logger.info(f"Error checking resource link {r.get('url')}: {exc}")
    return valid