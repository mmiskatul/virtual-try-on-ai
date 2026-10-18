from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ...adapters.registry import ModelRegistry

class SetDefaultModelRequest(BaseModel):
    model_name: str

def create_models_router(registry: ModelRegistry) -> APIRouter:
    r = APIRouter(prefix="/api/v1/models", tags=["Models"])

    @r.get("")
    async def list_models():
        return {"models": registry.list_models()}

    @r.post("/default")
    async def set_default_model(req: SetDefaultModelRequest):
        try:
            registry.set_default(req.model_name)
            return {"status": "success", "default_model": req.model_name}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return r
