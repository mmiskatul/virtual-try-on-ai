from fastapi import APIRouter
from ...adapters.registry import ModelRegistry

router = APIRouter()

def create_health_router(registry: ModelRegistry) -> APIRouter:
    r = APIRouter(tags=["Health"])

    @r.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def root():
        return {
            "service": "ai-virtual-try-on",
            "status": "running",
            "version": "1.0.0",
            "message": "AI Virtual Try-On service is running.",
            "endpoints": {
                "health": "/health",
                "models": "/api/v1/models",
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
