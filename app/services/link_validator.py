"""Checks that a resource URL actually resolves — and isn't a forum/social
post — before it reaches the user.

Used to catch three separate sources of bad links: stale results from the
live web search, low-signal domains (reddit, random video hosts, etc.) that
happen to rank for a vague query, and URLs an LLM invented despite being
told not to.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import socket
from typing import Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import re

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
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    if _is_blocked_domain(url):
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            return False
        resp = requests.head(url, allow_redirects=False, timeout=_TIMEOUT_SECONDS, headers=_HEADERS)
        if resp.status_code < 400:
            return True
        resp = requests.get(
            url, allow_redirects=False, timeout=_TIMEOUT_SECONDS, headers=_HEADERS, stream=True
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


_SKILL_ALIASES = {
    "js": "javascript",
    "node": "nodejs",
    "node.js": "nodejs",
    "react.js": "react",
}

# Generic instructional words must not count as evidence that a resource is
# relevant. Without this list, "Machine Learning for Everybody" can pass as a
# resource for "Deep Learning" simply because both contain the word learning.
_RESOURCE_STOPWORDS = {
    "the", "and", "for", "with", "from", "to", "of", "in", "on", "a", "an",
    "is", "are", "what", "how", "why", "by", "using", "use", "your", "you",
    "learn", "learning", "tutorial", "course", "courses", "complete", "full",
    "beginner", "beginners", "advanced", "guide", "guides", "introduction", "intro",
    "fundamentals", "basics", "explained", "explainer", "free", "video", "videos",
    "lesson", "lessons", "part", "series", "day", "need", "know", "official",
    "documentation", "docs", "training", "crash", "quick", "start", "started",
    "step", "steps", "everything", "overview", "easy", "simple", "best",
}


def _normalize_phrase(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


# Topic-specific alternatives support legitimate resources whose title does not
# repeat the catalog skill name verbatim. These aliases are intentionally
# discriminative: "machine learning" is not an alias for "deep learning" or
# "transfer learning" by itself.
_TOPIC_ALIASES = {
    "command line shell scripting": ("bash", "shell scripting", "command line", "terminal commands", "powershell"),
    "version control git": ("git", "github", "version control", "git branching"),
    "browser devtools": ("browser devtools", "chrome devtools", "developer tools", "devtools"),
    "python basics": ("python", "python programming", "python basics"),
    "data structures algorithms": ("data structures and algorithms", "algorithms", "time complexity", "big o notation"),
    "software architecture": ("software architecture", "system architecture", "layered architecture", "architecture patterns"),
    "nosql databases": ("nosql", "mongodb", "document database", "dynamodb", "cassandra"),
    "cloud fundamentals": ("cloud computing", "cloud fundamentals", "aws cloud", "google cloud", "azure cloud"),
    "cloud storage cdn": ("cloud storage", "content delivery network", "cdn", "amazon s3", "cloudflare"),
    "observability monitoring": ("observability", "application monitoring", "logs metrics traces", "monitoring and logging"),
    "frontend performance": ("web performance", "frontend performance", "lighthouse", "core web vitals", "performance optimization"),
    "data wrangling with pandas": ("pandas", "data wrangling", "data cleaning"),
    "sql for data science": ("sql", "sql queries", "relational databases"),
    "exploratory data analysis": ("exploratory data analysis", "eda", "data exploration", "exploratory analysis"),
    "feature engineering": ("feature engineering", "feature creation", "feature selection", "feature transformation", "feature preprocessing"),
    "linear algebra": ("linear algebra", "linear transformations", "matrix multiplication", "matrices"),
    "probability theory2": ("probability theory", "probability distributions", "bayes theorem", "bayes' theorem"),
    "statistics": ("statistics", "statistical inference", "descriptive statistics", "hypothesis testing"),
    "machine learning fundamentals": ("machine learning", "machine-learning", "ml fundamentals"),
    "linear logistic regression": ("linear regression", "logistic regression"),
    "decision trees random forests": ("decision tree", "random forest", "random forests"),
    "neural networks basics": ("neural network", "neural networks", "perceptron", "backpropagation", "feedforward network"),
    "deep learning": ("deep learning", "deep neural network", "neural networks", "pytorch", "tensorflow", "keras", "convolutional neural network", "transformer networks"),
    "model evaluation metrics": ("model evaluation", "evaluation metrics", "classification metrics", "confusion matrix", "precision and recall", "roc curve", "roc auc", "cross validation", "model validation"),
    "hyperparameter tuning": ("hyperparameter tuning", "grid search", "random search", "bayesian optimization", "optuna"),
    "explainable ai": ("explainable ai", "explainable artificial intelligence", "model interpretability", "shap", "lime", "feature attribution"),
    "ai ethics fairness": ("ai ethics", "responsible ai", "algorithmic fairness", "fairness in machine learning", "bias in machine learning", "fairness metrics"),
    "transfer learning": ("transfer learning", "pretrained model", "pre trained model", "fine tuning", "fine tuning", "feature extraction"),
    "mlops": ("mlops", "machine learning operations", "ml pipeline", "machine learning pipeline", "model deployment", "model monitoring", "model registry"),
    "containerization with docker": ("docker", "dockerfile", "docker compose", "containerization"),
    "ci cd pipelines": ("ci cd", "continuous integration", "continuous delivery", "github actions", "gitlab ci", "jenkins pipeline"),
    "javascript fundamentals": ("javascript", "ecmascript", "javascript basics"),
    "typescript": ("typescript", "tsconfig", "typescript types"),
    "react js": ("react.js", "reactjs", "react hooks", "react components", "react.dev"),
    "node js express": ("node.js", "nodejs", "express.js", "express framework", "express router"),
    "restful api development": ("rest api", "restful api", "api endpoints", "http api", "building apis"),
    "api design": ("api design", "rest api design", "http api design"),
    "responsive web design": ("responsive web design", "responsive design", "css media queries", "flexbox", "css grid"),
    "css frameworks tailwind": ("tailwind css", "tailwindcss"),
    "testing frontend apps": ("frontend testing", "react testing", "testing library", "vitest", "jest"),
    "web accessibility a11y": ("web accessibility", "accessibility", "a11y", "aria attributes", "accessible web"),
    "database programming": ("database programming", "sql queries", "postgresql", "mysql", "sqlite", "database queries"),
    "authentication authorization": ("authentication", "authorization", "jwt authentication", "session authentication", "oauth"),
    "web security": ("web security", "owasp", "cross site scripting", "xss", "csrf", "sql injection", "security headers"),
}
_NORMALIZED_TOPIC_ALIASES = {
    _normalize_phrase(skill): tuple(_normalize_phrase(alias) for alias in aliases)
    for skill, aliases in _TOPIC_ALIASES.items()
}


def _skill_tokens(value: str) -> set:
    normalized = (value or "").casefold().replace("react.js", "react").replace("node.js", "nodejs")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return {
        _SKILL_ALIASES.get(token, token)
        for token in tokens
        if len(token) > 1 and token not in _RESOURCE_STOPWORDS
    }


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return f" {phrase} " in f" {_normalize_phrase(text)} "


def _resource_matches_skill(resource: Dict, skill: str) -> bool:
    """Match against resource evidence, never the search query's skill tag.

    `skill` metadata is only a record of what we searched for; it is not proof
    that a search result actually teaches that topic. Relevance is assessed
    from the page title, result snippet/content, and URL instead.
    """
    evidence = " ".join(str(resource.get(key, "")) for key in ("title", "content", "url"))
    evidence_norm = _normalize_phrase(evidence)
    skill_norm = _normalize_phrase(skill)

    # Hand-picked resources are trusted for the skill they were curated for.
    if resource.get("curated") and _normalize_phrase(resource.get("matched_skill", "")) == skill_norm:
        return True

    aliases = _NORMALIZED_TOPIC_ALIASES.get(skill_norm)
    if aliases:
        return any(_contains_phrase(evidence_norm, alias) for alias in aliases)

    skill_tokens = _skill_tokens(skill)
    resource_tokens = _skill_tokens(evidence)
    if not skill_tokens:
        return False
    overlap = len(skill_tokens & resource_tokens)
    # One shared word is too weak for multiword skills. Require all meaningful
    # tokens for short names, and at least 60% for longer ones.
    required = len(skill_tokens) if len(skill_tokens) <= 2 else max(2, (len(skill_tokens) * 3 + 4) // 5)
    return overlap >= required


def _resource_matches_phase(resource: Dict, phase_skills: List[str], verified_by_url: Dict) -> bool:
    candidate = verified_by_url.get(resource.get("url", ""), resource)
    return any(_resource_matches_skill(candidate, skill) for skill in phase_skills)


def filter_relevant_resources(resources: List[Dict], phase_skills: List[str], verified_resources: List[Dict] = None, limit: int = 3) -> List[Dict]:
    """Keep resources with topic-specific evidence for at least one phase skill.

    When verified candidates are supplied, their canonical title/content take
    precedence over any title the LLM may have generated for the same URL.
    """
    if not phase_skills:
        return []
    verified_by_url = {item.get("url"): item for item in (verified_resources or []) if item.get("url")}
    selected = []
    seen = set()
    for resource in resources or []:
        url = resource.get("url", "")
        if url in seen or not _resource_matches_phase(resource, phase_skills, verified_by_url):
            continue
        canonical = verified_by_url.get(url, resource)
        selected.append({key: canonical.get(key, "") for key in ("title", "url", "type")})
        seen.add(url)
        if len(selected) >= limit:
            return selected
    for resource in verified_resources or []:
        url = resource.get("url", "")
        if len(selected) >= limit:
            break
        if url and url not in seen and _resource_matches_phase(resource, phase_skills, verified_by_url):
            selected.append({key: resource.get(key, "") for key in ("title", "url", "type")})
            seen.add(url)
    return selected[:limit]

def deduplicate_resources_across_phases(roadmap: Dict) -> Dict:
    """Keep the first occurrence of a resource across the entire roadmap."""
    seen = set()
    for phase in roadmap.get("phases", []) or []:
        unique_resources = []
        for resource in phase.get("resources", []) or []:
            parsed = urlparse(resource.get("url", ""))
            query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query) if key.lower() not in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}))
            key = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", query, ""))
            if not key or key in seen:
                continue
            seen.add(key)
            unique_resources.append(resource)
        phase["resources"] = unique_resources
    return roadmap