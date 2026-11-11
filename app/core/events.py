from datetime import datetime, timezone
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class StorageObjectRef(BaseModel):
    bucket: str = Field(min_length=1)
    objectKey: str = Field(min_length=1)
    contentType: str = Field(default="image/jpeg")


class ModelConfigRef(BaseModel):
    modelKey: str = Field(default="default-tryon")
    modelVersion: str = Field(default="v1")


class TryOnOptions(BaseModel):
    category: str = Field(default="tops")
    quality: Literal["fast_preview", "standard", "high_fidelity"] = "standard"
    prompt: Optional[str] = None


class TryOnGenerationRequestedV1(BaseModel):
    eventId: str
    eventType: Literal["tryon.generation.requested"] = "tryon.generation.requested"
    eventVersion: Literal[1] = 1
    occurredAt: str
    correlationId: str
    generationId: str
    tenantId: str
    userId: str
    personImage: StorageObjectRef
    garmentImage: StorageObjectRef
    modelConfig: ModelConfigRef = Field(default_factory=ModelConfigRef)
    options: TryOnOptions = Field(default_factory=TryOnOptions)


class GeneratedResultMeta(StorageObjectRef):
    width: Optional[int] = None
    height: Optional[int] = None


class GenerationStageMetrics(BaseModel):
    queueTimeMs: float = 0.0
    preprocessingTimeMs: float = 0.0
    inferenceTimeMs: float = 0.0
    postprocessingTimeMs: float = 0.0
    totalTimeMs: float = 0.0


class ExecutedModelMeta(BaseModel):
    key: str
    version: str


class TryOnGenerationCompletedV1(BaseModel):
    eventId: str
    eventType: Literal["tryon.generation.completed"] = "tryon.generation.completed"
    eventVersion: Literal[1] = 1
    occurredAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlationId: str
    generationId: str
    status: Literal["completed"] = "completed"
    result: GeneratedResultMeta
    metrics: GenerationStageMetrics
    model: ExecutedModelMeta


class GenerationErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False


class TryOnFailureMetrics(BaseModel):
    totalTimeMs: float = 0.0


class TryOnGenerationFailedV1(BaseModel):
    eventId: str
    eventType: Literal["tryon.generation.failed"] = "tryon.generation.failed"
    eventVersion: Literal[1] = 1
    occurredAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlationId: str
    generationId: str
    error: GenerationErrorDetail
    metrics: TryOnFailureMetrics


class PlatformTestPingV1(BaseModel):
    eventId: str
    eventType: Literal["platform.test.ping"] = "platform.test.ping"
    eventVersion: Literal[1] = 1
    occurredAt: str
    correlationId: str
    source: str
    payload: Dict[str, Any] = Field(default_factory=dict)

