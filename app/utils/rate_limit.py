"""Route-aware request rate limiting with a shared Redis backend in production.

Development and tests may use the process-local fallback. Production requires
RATE_LIMIT_REDIS_URL so limits are shared across workers and instances.
"""
import logging
import math
import re
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.config import settings

logger = logging.getLogger("learning_path_generator.rate_limit")

# Each pattern identifies an action group rather than an individual URL. In
# particular, quiz generation/submission URLs are matched by their structure,
# not by a broad substring such as "/quiz".
LIMITS = (
    ("auth-login", re.compile(r"^/auth/(?:login|login-form)$"), 10, 60),
    ("auth-register", re.compile(r"^/auth/register$"), 5, 300),
    ("auth-forgot-password", re.compile(r"^/auth/forgot-password$"), 5, 300),
    ("chat", re.compile(r"^/chat(?:/history|/stream|/explain-answer)?$"), 30, 60),
    ("roadmap-generate", re.compile(r"^/roadmap/generate-roadmap(?:/async)?$"), 5, 300),
    ("quiz", re.compile(r"^/roadmap/[^/]+/phase/\d+/quiz(?:/submit)?$"), 20, 60),
    ("share-public", re.compile(r"^/share/[^/]+$"), 60, 60),
)

_REDIS_INCR_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('PTTL', KEYS[1])
return {count, ttl}
"""


class RequestRateLimitMiddleware(BaseHTTPMiddleware):
    """Atomic shared limits via Redis; memory fallback is development-only."""

    def __init__(self, app):
        super().__init__(app)
        self._requests = defaultdict(deque)
        self._lock = Lock()
        self._redis = None
        redis_url = getattr(settings, "RATE_LIMIT_REDIS_URL", "")
        if redis_url:
            try:
                from redis.asyncio import Redis
            except ImportError as exc:  # pragma: no cover - configuration error
                raise RuntimeError(
                    "RATE_LIMIT_REDIS_URL is configured but redis is not installed. "
                    "Install requirements.txt to enable shared rate limiting."
                ) from exc
            self._redis = Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _limit_for(path):
        for bucket, pattern, maximum, window_seconds in LIMITS:
            if pattern.fullmatch(path):
                return bucket, maximum, window_seconds
        return None

    def _consume_local(self, key, maximum, window_seconds, now):
        """Process-local fallback for development/test only."""
        with self._lock:
            recent = self._requests[key]
            while recent and now - recent[0] >= window_seconds:
                recent.popleft()
            if len(recent) >= maximum:
                return False, max(1, math.ceil(window_seconds - (now - recent[0])))
            recent.append(now)
            # Bound stale keys so a long-running dev server does not grow forever.
            if len(self._requests) > 4096:
                cutoff = now - max(window for _, _, _, window in LIMITS)
                for old_key in list(self._requests.keys())[:1024]:
                    queue = self._requests[old_key]
                    while queue and queue[0] <= cutoff:
                        queue.popleft()
                    if not queue:
                        self._requests.pop(old_key, None)
            return True, 0

    async def _consume(self, key, maximum, window_seconds):
        if self._redis is not None:
            count, ttl_ms = await self._redis.eval(
                _REDIS_INCR_SCRIPT, 1, key, int(window_seconds * 1000)
            )
            return int(count) <= maximum, max(1, math.ceil(max(0, int(ttl_ms)) / 1000))
        if settings.ENVIRONMENT.lower() not in {"development", "test"}:
            # Fail closed if someone bypasses the configuration guard.
            raise RuntimeError("Shared rate limiting requires RATE_LIMIT_REDIS_URL outside development.")
        return self._consume_local(key, maximum, window_seconds, time.monotonic())

    async def dispatch(self, request: Request, call_next):
        matched = self._limit_for(request.url.path)
        if not matched:
            return await call_next(request)

        bucket, maximum, window_seconds = matched
        client = request.client.host if request.client else "unknown"
        key = f"rate-limit:{bucket}:{client}"
        try:
            allowed, ttl = await self._consume(key, maximum, window_seconds)
        except Exception as exc:
            logger.error("Rate-limit backend unavailable for bucket %s: %s", bucket, exc)
            return JSONResponse(
                status_code=503,
                content={"detail": "Request protection is temporarily unavailable. Please retry shortly."},
                headers={"Retry-After": "5"},
            )

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={"Retry-After": str(ttl or window_seconds)},
            )
        return await call_next(request)
