from fastapi import APIRouter
from ...adapters.registry import ModelRegistry
from ...core.events import PlatformTestPingV1, TryOnGenerationRequestedV1
from ...services.pipeline import TryOnPipeline


def create_internal_router(registry: ModelRegistry, pipeline: TryOnPipeline) -> APIRouter:
    r = APIRouter(prefix="/internal/v1", tags=["Internal Service Bus"])

    @r.get("/worker/health")
    async def worker_health():
        return {
            "status": "ready",
            "storageDriver": pipeline.storage.driver_name,
            "models": registry.list_models(),
        }

    @r.post("/events/ping")
    async def ping_event(payload: PlatformTestPingV1):
        return {
            "eventType": "platform.test.pong",
            "correlationId": payload.correlationId,
            "pingEventId": payload.eventId,
            "modelsAvailable": len(registry.list_models()),
        }

    @r.post("/try-on/execute")
    async def execute_storage_job(payload: TryOnGenerationRequestedV1):
        outcome = await pipeline.process_event(payload)
        return outcome.model_dump()

    return r

