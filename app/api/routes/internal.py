import hmac
from fastapi import APIRouter, Header, HTTPException
from ...adapters.registry import ModelRegistry
from ...core.config import settings
from ...core.events import PlatformTestPingV1, TryOnGenerationRequestedV1
from ...services.pipeline import TryOnPipeline

def _verify_service_key(x_service_key: str | None) -> None:
    if not x_service_key:
        raise HTTPException(status_code=401, detail="Missing X-Service-Key internal authentication header.")
    if not hmac.compare_digest(x_service_key, settings.internal_service_key):
        raise HTTPException(status_code=403, detail="Invalid internal service authentication credential.")


def create_internal_router(registry: ModelRegistry, pipeline: TryOnPipeline) -> APIRouter:
    r = APIRouter(prefix="/internal/v1", tags=["Internal Service Bus"])

    @r.get("/worker/health")
    async def worker_health(x_service_key: str | None = Header(default=None)):
        _verify_service_key(x_service_key)
        return {
            "status": "ready",
            "storageDriver": pipeline.storage.driver_name,
            "models": registry.list_models(),
        }

    @r.post("/events/ping")
    async def ping_event(
        payload: PlatformTestPingV1,
        x_service_key: str | None = Header(default=None),
    ):
        _verify_service_key(x_service_key)
        return {
            "eventType": "platform.test.pong",
            "correlationId": payload.correlationId,
            "pingEventId": payload.eventId,
            "modelsAvailable": len(registry.list_models()),
        }

    @r.post("/try-on/execute")
    async def execute_storage_job(
        payload: TryOnGenerationRequestedV1,
        x_service_key: str | None = Header(default=None),
    ):
        _verify_service_key(x_service_key)
        outcome = await pipeline.process_event(payload)
        return outcome.model_dump()

    return r

