from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from typing import Optional
from ...services.job_queue import JobManager
from ...core.config import settings
from ...core.sanitizer import inspect_string

def create_try_on_router(job_manager: JobManager) -> APIRouter:
    r = APIRouter(tags=["Virtual Try-On"])

    @r.post("/api/v1/try-on/jobs")
    async def create_try_on_job(
        background_tasks: BackgroundTasks,
        person_image: UploadFile = File(..., description="User full or upper body photograph"),
        garment_image: UploadFile = File(..., description="Garment product apparel photograph"),
        category: str = Form("tops", description="Garment category: tops, bottoms, dresses, outerwear"),
        model_name: Optional[str] = Form(None, description="Optional target model adapter name"),
    ):
        # Validate form inputs against injections
        for field_name, field_val in [("category", category), ("model_name", model_name), ("person_filename", person_image.filename), ("garment_filename", garment_image.filename)]:
            if field_val:
                threat = inspect_string(field_val, field_name)
                if threat:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "SecurityViolation",
                            "code": f"INJECTION_ATTACK_DETECTED_{threat['threat_type']}",
                            "message": f"Malicious {threat['threat_type']} payload blocked in form field '{field_name}'."
                        }
                    )

        try:
            person_bytes = await person_image.read()
            garment_bytes = await garment_image.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read image payloads: {str(e)}")

        if len(person_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(status_code=400, detail="Person image exceeds 10MB limit.")
        if len(garment_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(status_code=400, detail="Garment image exceeds 10MB limit.")

        job = job_manager.create_job(
            category=category.lower(),
            person_bytes=person_bytes,
            garment_bytes=garment_bytes,
            person_filename=person_image.filename or "person.jpg",
            garment_filename=garment_image.filename or "garment.jpg",
        )

        background_tasks.add_task(job_manager.execute_job, job.job_id, model_name)

        return {
            "job_id": job.job_id,
            "status": job.status,
            "category": job.category,
            "message": "Virtual try-on job submitted successfully",
            "created_at": job.created_at,
            "poll_url": f"/api/v1/try-on/jobs/{job.job_id}",
        }

    @r.get("/api/v1/try-on/jobs/{job_id}")
    async def get_try_on_job(job_id: str):
        job = job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Try-on job '{job_id}' not found.")
        return job.to_dict()

    @r.post("/api/v1/try-on/jobs/{job_id}/cancel")
    async def cancel_try_on_job(job_id: str):
        cancelled = job_manager.cancel_job(job_id)
        if not cancelled:
            raise HTTPException(status_code=400, detail="Job cannot be cancelled (either not found or already terminated).")
        return {"status": "cancelled", "job_id": job_id}

    @r.post("/api/v1/try-on")
    async def process_try_on_sync(
        person_image: UploadFile = File(..., description="User person photo"),
        garment_image: UploadFile = File(..., description="Garment product image"),
        category: Optional[str] = Form("tops", description="Garment category: tops, bottoms, dresses"),
    ):
        for field_name, field_val in [("category", category), ("person_filename", person_image.filename), ("garment_filename", garment_image.filename)]:
            if field_val:
                threat = inspect_string(field_val, field_name)
                if threat:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "SecurityViolation",
                            "code": f"INJECTION_ATTACK_DETECTED_{threat['threat_type']}",
                            "message": f"Malicious {threat['threat_type']} payload blocked in form field '{field_name}'."
                        }
                    )

        person_bytes = await person_image.read()
        garment_bytes = await garment_image.read()
        
        job = job_manager.create_job(
            category=category.lower() if category else "tops",
            person_bytes=person_bytes,
            garment_bytes=garment_bytes,
            person_filename=person_image.filename or "person.jpg",
            garment_filename=garment_image.filename or "garment.jpg",
        )
        
        await job_manager.execute_job(job.job_id)
        updated = job_manager.get_job(job.job_id)
        return updated.to_dict() if updated else {}

    return r
