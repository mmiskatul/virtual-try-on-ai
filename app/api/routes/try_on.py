import os
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Request, Response
from ...services.job_queue import JobManager
from ...services.image_loader import resolve_image_payload
from ...core.config import settings
from ...core.sanitizer import inspect_string
from ...core.idempotency import idempotency_manager

def create_try_on_router(job_manager: JobManager) -> APIRouter:
    r = APIRouter(tags=["Virtual Try-On"])

    @r.post("/api/v1/try-on/jobs")
    @r.post("/api/v1/tryon/jobs")
    async def create_try_on_job(
        request: Request,
        response: Response,
        background_tasks: BackgroundTasks,
        person_image: Optional[UploadFile] = File(None, description="User full or upper body photograph"),
        garment_image: Optional[UploadFile] = File(None, description="Garment product apparel photograph"),
        category: Optional[str] = Form(None, description="Garment category: tops, bottoms, dresses, outerwear"),
        model_name: Optional[str] = Form(None, description="Optional target model adapter name"),
        prompt: Optional[str] = Form(None, description="Optional styling prompt for AI try-on"),
    ):
        content_type = request.headers.get("content-type", "").lower()
        person_input = person_image
        garment_input = garment_image
        cat_str = category or "tops"
        target_model = model_name
        prompt_str = prompt

        # Parse JSON payload if sent as application/json
        if "application/json" in content_type:
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body payload.")

            if isinstance(body, dict):
                person_input = (
                    body.get("personImage")
                    or body.get("person_image")
                    or body.get("userImageUrl")
                    or body.get("user_image_url")
                    or body.get("person")
                )
                garment_input = (
                    body.get("garmentImage")
                    or body.get("garment_image")
                    or body.get("garmentImageUrl")
                    or body.get("garment_image_url")
                    or body.get("garment")
                )
                cat_str = body.get("category") or body.get("clothType") or cat_str
                target_model = body.get("model_name") or body.get("modelName") or target_model
                prompt_str = body.get("prompt") or body.get("instruction") or prompt_str

        # Security inspection on text fields
        for field_name, field_val in [
            ("category", cat_str),
            ("model_name", target_model),
            ("prompt", prompt_str),
            ("person_filename", getattr(person_image, "filename", None)),
            ("garment_filename", getattr(garment_image, "filename", None)),
        ]:
            if field_val and isinstance(field_val, str):
                threat = inspect_string(field_val, field_name)
                if threat:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "SecurityViolation",
                            "code": f"INJECTION_ATTACK_DETECTED_{threat['threat_type']}",
                            "message": f"Malicious {threat['threat_type']} payload blocked in field '{field_name}'."
                        }
                    )

        # Resolve image payloads (UploadFile, data URI, URL, or fallback)
        person_bytes, p_name = await resolve_image_payload(person_input, fallback_type="person")
        garment_bytes, g_name = await resolve_image_payload(garment_input, fallback_type="garment", category=cat_str)

        if len(person_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(status_code=400, detail="Person image exceeds 10MB limit.")
        if len(garment_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(status_code=400, detail="Garment image exceeds 10MB limit.")

        # Idempotency verification
        idempotency_key = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
        req_hash = None
        if idempotency_key:
            req_hash = idempotency_manager.compute_hash(
                cat_str.encode("utf-8"),
                (target_model or "").encode("utf-8"),
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
            category=cat_str.lower(),
            person_bytes=person_bytes,
            garment_bytes=garment_bytes,
            person_filename=p_name or "person.jpg",
            garment_filename=g_name or "garment.jpg",
            prompt=prompt_str,
        )

        background_tasks.add_task(job_manager.execute_job, job.job_id, target_model)

        result_payload = {
            "job_id": job.job_id,
            "jobId": job.job_id,
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
    @r.get("/api/v1/tryon/jobs/{job_id}")
    async def get_try_on_job(job_id: str):
        job = job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Try-on job '{job_id}' not found.")
        return job.to_dict()

    @r.post("/api/v1/try-on/jobs/{job_id}/cancel")
    @r.post("/api/v1/tryon/jobs/{job_id}/cancel")
    async def cancel_try_on_job(job_id: str):
        cancelled = job_manager.cancel_job(job_id)
        if not cancelled:
            raise HTTPException(status_code=400, detail="Job cannot be cancelled (either not found or already terminated).")
        return {"status": "cancelled", "job_id": job_id}

    @r.post("/api/v1/try-on")
    @r.post("/api/v1/tryon")
    async def process_try_on_sync(
        request: Request,
        person_image: Optional[UploadFile] = File(None, description="User person photo"),
        garment_image: Optional[UploadFile] = File(None, description="Garment product image"),
        category: Optional[str] = Form("tops", description="Garment category: tops, bottoms, dresses"),
        model_name: Optional[str] = Form(None, description="Optional target model adapter name"),
        prompt: Optional[str] = Form(None, description="Optional styling prompt"),
    ):
        content_type = request.headers.get("content-type", "").lower()
        person_input = person_image
        garment_input = garment_image
        cat_str = category or "tops"
        target_model = model_name
        prompt_str = prompt

        if "application/json" in content_type:
            try:
                body = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body payload.")
            if isinstance(body, dict):
                person_input = (
                    body.get("personImage")
                    or body.get("person_image")
                    or body.get("userImageUrl")
                    or body.get("user_image_url")
                    or body.get("person")
                )
                garment_input = (
                    body.get("garmentImage")
                    or body.get("garment_image")
                    or body.get("garmentImageUrl")
                    or body.get("garment_image_url")
                    or body.get("garment")
                )
                cat_str = body.get("category") or body.get("clothType") or cat_str
                target_model = body.get("model_name") or body.get("modelName") or target_model
                prompt_str = body.get("prompt") or body.get("instruction") or prompt_str

        # Resolve image bytes
        person_bytes, p_name = await resolve_image_payload(person_input, fallback_type="person")
        garment_bytes, g_name = await resolve_image_payload(garment_input, fallback_type="garment", category=cat_str)

        job = job_manager.create_job(
            category=cat_str.lower(),
            person_bytes=person_bytes,
            garment_bytes=garment_bytes,
            person_filename=p_name or "person.jpg",
            garment_filename=g_name or "garment.jpg",
            prompt=prompt_str,
        )
        
        await job_manager.execute_job(job.job_id, target_model)
        updated = job_manager.get_job(job.job_id)
        return updated.to_dict() if updated else {}

    @r.get("/api/v1/storage/status")
    async def get_storage_status():
        return {
            "provider": "local_disk",
            "storage_delegated_to_backend": True,
            "status": "ready",
            "note": "AI Service saves output locally or returns external generation URL. Cloudinary CDN persistence is managed centrally by Backend API."
        }

    @r.post("/api/v1/storage/upload")
    async def upload_image_direct(
        file: UploadFile = File(..., description="Image file to store locally in AI service"),
        folder: Optional[str] = Form(None)
    ):
        file_bytes = await file.read()
        if len(file_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(status_code=400, detail="Image exceeds max allowed upload size.")

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
            "note": "Stored in AI service local storage. Long-term CDN persistence managed by Backend Cloudinary adapter."
        }

    return r
