import io
import os
import time
import uuid
from typing import Union
from PIL import Image
from ..adapters.registry import ModelRegistry
from ..adapters.model_contract import AdapterTryOnModelBridge
from ..core.events import (
    ExecutedModelMeta,
    GeneratedResultMeta,
    GenerationErrorDetail,
    GenerationStageMetrics,
    TryOnGenerationCompletedV1,
    TryOnGenerationFailedV1,
    TryOnGenerationRequestedV1,
    TryOnFailureMetrics,
)
from .storage_adapter import PrivateStorageAdapter, private_storage


def validate_decoded_image(raw_bytes: bytes, label: str, max_bytes: int = 10 * 1024 * 1024) -> Image.Image:
    if not raw_bytes:
        raise ValueError(f"{label} payload is empty.")
    if len(raw_bytes) > max_bytes:
        raise ValueError(f"{label} exceeds maximum size limit.")
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.verify()
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
        return img
    except Exception as exc:
        raise ValueError(f"{label} image failed integrity decoding: {exc}")


class TryOnPipeline:
    """Modular async Virtual Try-On execution pipeline (Storage -> Validate -> Infer -> Private Output)."""

    def __init__(
        self,
        registry: ModelRegistry,
        output_dir: str,
        storage: PrivateStorageAdapter = private_storage,
    ):
        self.registry = registry
        self.output_dir = output_dir
        self.storage = storage

    async def process_event(
        self, req: TryOnGenerationRequestedV1
    ) -> Union[TryOnGenerationCompletedV1, TryOnGenerationFailedV1]:
        t0 = time.perf_counter()
        try:
            # 1. Fetch inputs securely from private storage references
            person_bytes = await self.storage.download_bytes(req.personImage.bucket, req.personImage.objectKey)
            garment_bytes = await self.storage.download_bytes(req.garmentImage.bucket, req.garmentImage.objectKey)

            # 2. Decode & validate image integrity + dimensions
            person_img = validate_decoded_image(person_bytes, "personImage")
            garment_img = validate_decoded_image(garment_bytes, "garmentImage")
            t_pre = time.perf_counter()

            # 3. Route model per Fastify-authorized modelKey
            model_key = None if req.modelConfig.modelKey == "default-tryon" else req.modelConfig.modelKey
            adapter = self.registry.get_model(model_key)
            contract = AdapterTryOnModelBridge(adapter, self.output_dir)

            # 4. Execute inference & postprocess cleanly
            result = await contract.generate(
                person_img,
                garment_img,
                {
                    "job_id": req.generationId,
                    "category": req.options.category,
                    "quality": req.options.quality,
                    "prompt": req.options.prompt,
                },
            )
            t_inf = time.perf_counter()

            if result.status != "completed" or not result.output_image_path or not os.path.exists(result.output_image_path):
                return TryOnGenerationFailedV1(
                    eventId=f"evt_{uuid.uuid4().hex}",
                    correlationId=req.correlationId,
                    generationId=req.generationId,
                    error=GenerationErrorDetail(
                        code="MODEL_INFERENCE_FAILED",
                        message=result.error or "Virtual try-on synthesis could not complete.",
                        retryable=True,
                    ),
                    metrics=TryOnFailureMetrics(totalTimeMs=round((time.perf_counter() - t0) * 1000, 2)),
                )

            # 5. Read result, encode PNG/JPEG cleanly & persist to private storage bucket
            with open(result.output_image_path, "rb") as f:
                out_bytes = f.read()
            out_img = validate_decoded_image(out_bytes, "outputImage", max_bytes=20 * 1024 * 1024)
            width, height = out_img.size

            dest_key = f"{req.tenantId}/{req.generationId}/result.jpg"
            await self.storage.upload_bytes("generated-results", dest_key, out_bytes, "image/jpeg")

            # Clean temporary local file after durable private bucket upload
            try:
                os.remove(result.output_image_path)
            except OSError:
                pass

            t_end = time.perf_counter()
            return TryOnGenerationCompletedV1(
                eventId=f"evt_{uuid.uuid4().hex}",
                correlationId=req.correlationId,
                generationId=req.generationId,
                result=GeneratedResultMeta(
                    bucket="generated-results",
                    objectKey=dest_key,
                    contentType="image/jpeg",
                    width=width,
                    height=height,
                ),
                metrics=GenerationStageMetrics(
                    queueTimeMs=0.0,
                    preprocessingTimeMs=round((t_pre - t0) * 1000, 2),
                    inferenceTimeMs=round((t_inf - t_pre) * 1000, 2),
                    postprocessingTimeMs=round((t_end - t_inf) * 1000, 2),
                    totalTimeMs=round((t_end - t0) * 1000, 2),
                ),
                model=ExecutedModelMeta(
                    key=result.model_name or adapter.name,
                    version=result.model_version or adapter.version,
                ),
            )
        except ValueError as val_err:
            return TryOnGenerationFailedV1(
                eventId=f"evt_{uuid.uuid4().hex}",
                correlationId=req.correlationId,
                generationId=req.generationId,
                error=GenerationErrorDetail(
                    code="INPUT_VALIDATION_ERROR",
                    message=str(val_err),
                    retryable=False,
                ),
                metrics=TryOnFailureMetrics(totalTimeMs=round((time.perf_counter() - t0) * 1000, 2)),
            )
        except Exception as err:
            return TryOnGenerationFailedV1(
                eventId=f"evt_{uuid.uuid4().hex}",
                correlationId=req.correlationId,
                generationId=req.generationId,
                error=GenerationErrorDetail(
                    code="WORKER_EXECUTION_ERROR",
                    message="Internal AI execution failure.",
                    retryable=True,
                ),
                metrics=TryOnFailureMetrics(totalTimeMs=round((time.perf_counter() - t0) * 1000, 2)),
            )

