"""
Service-to-service authentication for the AI engine.

Every request must carry the shared secret in the `X-Service-Key` header (INTERNAL_SERVICE_KEY),
which only the backend knows. Without it the engine would let anyone on the internet run paid
try-on generations and read its metrics and API docs.

Public (no key): /health, /live, /ready probes, the generated result images under /static/
(the backend's image CDN fetches them), CORS preflight, and a minimal status on "/".

Fail-closed: if INTERNAL_SERVICE_KEY is not configured the protected routes answer 503, unless
ALLOW_UNAUTHENTICATED_DEV=true is set explicitly (local development only).
"""
import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("service_auth")

SERVICE_KEY_HEADER = "x-service-key"
PUBLIC_EXACT = {"/health", "/live", "/ready"}
PUBLIC_PREFIXES = ("/static/",)

_warned_unconfigured = False


def _valid(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


class ServiceKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global _warned_unconfigured
        path = request.url.path

        if request.method == "OPTIONS" or path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        expected = os.getenv("INTERNAL_SERVICE_KEY", "").strip()
        provided = request.headers.get(SERVICE_KEY_HEADER, "").strip()

        if not expected:
            if os.getenv("ALLOW_UNAUTHENTICATED_DEV", "").strip().lower() == "true":
                if not _warned_unconfigured:
                    logger.warning("INTERNAL_SERVICE_KEY is not set: running UNAUTHENTICATED (development only).")
                    _warned_unconfigured = True
                return await call_next(request)
            if path == "/":
                return JSONResponse({"service": "ai-virtual-try-on", "status": "running"})
            return JSONResponse(
                status_code=503,
                content={"error": "ServiceNotConfigured", "message": "Service authentication is not configured."},
            )

        if provided and _valid(provided, expected):
            return await call_next(request)

        if path == "/":
            # Minimal public status page (host health checks): no versions, providers or paths.
            return JSONResponse({"service": "ai-virtual-try-on", "status": "running"})

        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "A valid service key is required."},
        )
