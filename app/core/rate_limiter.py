"""
Sliding-Window Rate Limiter Middleware for FastAPI / Starlette
Protects GPU inference workloads and asynchronous job submission queues against abuse and DDoS.
"""
import time
from typing import Dict, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class SlidingWindowRateLimiter:
    def __init__(self, standard_limit: int = 100, sensitive_limit: int = 20, window_seconds: int = 60):
        self.standard_limit = standard_limit
        self.sensitive_limit = sensitive_limit
        self.window_seconds = window_seconds
        self.store: Dict[str, Dict[str, float]] = {}
        self.last_cleanup = time.time()

    def _cleanup(self, now: float):
        if now - self.last_cleanup > 60:
            self.last_cleanup = now
            expired = [k for k, v in self.store.items() if v["reset_at"] <= now]
            for k in expired:
                del self.store[k]

    def reset(self):
        self.store.clear()

    def check(self, request: Request) -> Tuple[bool, int, int, int]:
        now = time.time()
        self._cleanup(now)

        path = request.url.path
        is_sensitive = "/try-on" in path or "/cancel" in path
        limit = self.sensitive_limit if is_sensitive else self.standard_limit

        client_ip = request.client.host if request.client else "127.0.0.1"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        auth = request.headers.get("authorization", "")
        key = f"{client_ip}:{'heavy' if is_sensitive else 'std'}:{auth[-10:] if auth else 'anon'}"

        record = self.store.get(key)
        if not record or record["reset_at"] <= now:
            reset_at = now + self.window_seconds
            self.store[key] = {"count": 1, "reset_at": reset_at}
            reset_sec = int(reset_at - now)
            return True, limit, limit - 1, reset_sec

        record["count"] += 1
        reset_sec = max(1, int(record["reset_at"] - now))
        remaining = max(0, limit - int(record["count"]))

        if record["count"] > limit:
            return False, limit, 0, reset_sec

        return True, limit, remaining, reset_sec


class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: SlidingWindowRateLimiter = None):
        super().__init__(app)
        self.limiter = limiter or SlidingWindowRateLimiter()

    async def dispatch(self, request: Request, call_next) -> Response:
        # Exclude health probe from rate limits
        if request.url.path in ("/", "/health"):
            return await call_next(request)

        allowed, limit, remaining, reset_sec = self.limiter.check(request)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "TooManyRequests",
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded. Too many requests. Please retry after {reset_sec} seconds.",
                    "retry_after": reset_sec,
                },
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_sec),
                    "Retry-After": str(reset_sec),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_sec)
        return response
