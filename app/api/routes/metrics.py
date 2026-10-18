from fastapi import APIRouter
from ...services.job_queue import JobManager

def create_metrics_router(job_manager: JobManager) -> APIRouter:
    r = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])

    @r.get("")
    async def get_ai_metrics():
        return {
            "engine": "FastAPI-VITON-Engine",
            **job_manager.get_metrics()
        }

    return r
