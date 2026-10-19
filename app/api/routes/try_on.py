import os
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Request, Response
from ...services.job_queue import JobManager
from ...services.cloudinary_storage import cloudinary_service
from ...core.config import settings
from ...core.sanitizer import inspect_string
from ...core.idempotency import idempotency_manager

def create_try_on_router(job_manager: JobManager) -> APIRouter:
    r = APIRouter(tags=["Virtual Try-On"])

    @r.post("/api/v1/try-on/jobs")
    async def create_try_on_job(
        request: Request,
        response: Response,
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

        # Idempotency verification
        idempotency_key = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
        req_hash = None
        if idempotency_key:
            req_hash = idempotency_manager.compute_hash(
                category.encode("utf-8"),
                (model_name or "").encode("utf-8"),
                person_bytes,
                garment_bytes
            )
            existing = idempotency_manager.get_record(idempotency_key)
            if existing:
                if existing.request_hash != req_hash:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "error": "UnprocessableEntity",
                            "code": "IDEMPOTENCY_PAYLOAD_MISMATCH",
                            "message": "Idempotency key was previously used with a different request payload."
                        }
                    )
                response.headers["idempotency-replay"] = "true"
                return existing.response_payload

        job = job_manager.create_job(
            category=category.lower(),
            person_bytes=person_bytes,
            garment_bytes=garment_bytes,
            person_filename=person_image.filename or "person.jpg",
            garment_filename=garment_image.filename or "garment.jpg",
        )

        background_tasks.add_task(job_manager.execute_job, job.job_id, model_name)

        result_payload = {
            "job_id": job.job_id,
            "status": job.status,
            "category": job.category,
            "message": "Virtual try-on job submitted successfully",
            "created_at": job.created_at,
            "poll_url": f"/api/v1/try-on/jobs/{job.job_id}",
        }

        if idempotency_key and req_hash:
            idempotency_manager.store_record(idempotency_key, req_hash, result_payload, 200)

        return result_payload


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

    @r.get("/api/v1/storage/status")
    async def get_storage_status():
        is_cloud = cloudinary_service.is_configured()
        return {
            "provider": "cloudinary" if is_cloud else "local_disk",
            "cloudinary_configured": is_cloud,
            "cloud_name": settings.cloudinary_cloud_name if is_cloud else None,
            "folder": settings.cloudinary_folder,
            "status": "ready"
        }

    @r.post("/api/v1/storage/upload")
    async def upload_image_direct(
        file: UploadFile = File(..., description="Image file to store on Cloudinary"),
        folder: Optional[str] = Form(None)
    ):
        file_bytes = await file.read()
        if len(file_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(status_code=400, detail="Image exceeds max allowed upload size.")

        cloudinary_url = cloudinary_service.upload_image(file_bytes, folder=folder)
        if cloudinary_url:
            return {
                "success": True,
                "provider": "cloudinary",
                "url": cloudinary_url,
                "filename": file.filename
            }

        import uuid
        local_filename = f"upload_{uuid.uuid4().hex[:10]}_{file.filename or 'image.jpg'}"
        local_path = os.path.join(settings.output_dir, local_filename)
        with open(local_path, "wb") as f:
            f.write(file_bytes)

        return {
            "success": True,
            "provider": "local_disk",
            "url": f"/static/results/{local_filename}",
            "filename": file.filename,
            "note": "Cloudinary not configured in .env; saved to local static storage."
        }

    return r
