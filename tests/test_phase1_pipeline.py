import io
import os
import tempfile
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import create_app
from app.core.config import settings
from app.core.events import PlatformTestPingV1, StorageObjectRef, TryOnGenerationRequestedV1
from app.adapters.registry import ModelRegistry
from app.services.pipeline import TryOnPipeline
from app.services.storage_adapter import PrivateStorageAdapter


def _make_img_bytes(color=(120, 140, 190), size=(360, 480)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_phase1_pipeline_and_private_storage():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PRIVATE_OBJECT_ROOT"] = tmp
        storage = PrivateStorageAdapter()
        assert storage.driver_name == "local_private"

        p_key = "user_1/up_1/person.jpg"
        g_key = "tenant_aura/prod_1/garment.jpg"
        await storage.upload_bytes("customer-uploads", p_key, _make_img_bytes((190, 150, 130)), "image/jpeg")
        await storage.upload_bytes("brand-assets", g_key, _make_img_bytes((30, 50, 110)), "image/jpeg")

        registry = ModelRegistry()
        pipeline = TryOnPipeline(registry=registry, output_dir=settings.output_dir, storage=storage)

        req = TryOnGenerationRequestedV1(
            eventId="evt_test_001",
            occurredAt="2026-11-11T12:00:00Z",
            correlationId="corr_test_001",
            generationId="gen_phase1_001",
            tenantId="tenant_aura",
            userId="user_1",
            personImage=StorageObjectRef(bucket="customer-uploads", objectKey=p_key),
            garmentImage=StorageObjectRef(bucket="brand-assets", objectKey=g_key),
        )

        outcome = await pipeline.process_event(req)
        assert outcome.eventType == "tryon.generation.completed"
        assert outcome.result.bucket == "generated-results"
        assert outcome.result.objectKey == "tenant_aura/gen_phase1_001/result.jpg"
        assert await storage.exists("generated-results", outcome.result.objectKey)

        with pytest.raises(ValueError):
            await storage.download_bytes("customer-uploads", "../../secrets.txt")


def test_internal_service_auth_and_ping_event():
    app = create_app()
    client = TestClient(app)

    # Rejects missing and invalid X-Service-Key
    assert client.get("/internal/v1/worker/health").status_code == 401
    assert client.get("/internal/v1/worker/health", headers={"X-Service-Key": "wrong_key"}).status_code == 403

    ok_health = client.get("/internal/v1/worker/health", headers={"X-Service-Key": settings.internal_service_key})
    assert ok_health.status_code == 200
    assert ok_health.json()["status"] == "ready"

    ping = PlatformTestPingV1(
        eventId="evt_ping_1",
        occurredAt="2026-11-11T12:00:00Z",
        correlationId="corr_ping_1",
        source="fastify-test",
        payload={"probe": True},
    )
    pong_res = client.post(
        "/internal/v1/events/ping",
        headers={"X-Service-Key": settings.internal_service_key},
        json=ping.model_dump(),
    )
    assert pong_res.status_code == 200
    assert pong_res.json()["eventType"] == "platform.test.pong"
    assert pong_res.json()["correlationId"] == "corr_ping_1"

