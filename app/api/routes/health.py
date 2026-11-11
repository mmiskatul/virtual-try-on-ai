import time
from datetime import datetime, timezone
from fastapi import APIRouter
from ...core.config import settings
from ...adapters.registry import ModelRegistry

router = APIRouter()
STARTED_AT = time.time()

def create_health_router(registry: ModelRegistry) -> APIRouter:
    r = APIRouter(tags=["Health"])

    @r.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def root():
        # Status only: never keys, URLs, or secrets.
        default_model = registry.get_model()
        return {
            "service": "ai-virtual-try-on",
            "description": settings.description,
            "version": settings.version,
            "status": "running",
            "environment": settings.env,
            "startedAt": datetime.fromtimestamp(STARTED_AT, tz=timezone.utc).isoformat(),
            "uptimeSeconds": int(time.time() - STARTED_AT),
            "activeModel": {"name": default_model.name, "version": default_model.version},
            "availableModels": len(registry.list_models()),
            "providers": {
                "gemini": "configured" if settings.gemini_api_key else "not configured",
                "fal": "configured" if settings.fal_key else "not configured",
                "falModel": settings.fal_model,
                "geminiModel": settings.gemini_model,
            },
            "endpoints": {
                "health": "/health",
                "models": "/api/v1/models",
                "tryOnJobs": "/api/v1/try-on/jobs",
                "metrics": "/api/v1/metrics",
                "docs": "/docs",
            },
        }

    @r.get("/health")
    async def health_check():
        models = registry.list_models()
        default_model = registry.get_model()
        return {
            "status": "healthy",
            "service": "ai-virtual-try-on",
            "version": "1.0.0",
            "active_model": default_model.name,
            "active_model_version": default_model.version,
            "available_models": len(models),
            "concurrency_ready": True,
        }

    return r
