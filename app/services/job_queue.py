import asyncio
import time
import uuid
import io
from typing import Dict, Any, Optional
from PIL import Image
from ..adapters.base import TryOnResult
from ..adapters.registry import ModelRegistry

class TryOnJob:
    def __init__(
        self,
        job_id: str,
        category: str,
        person_bytes: bytes,
        garment_bytes: bytes,
        person_filename: str = "person.jpg",
        garment_filename: str = "garment.jpg",
        prompt: Optional[str] = None,
    ):
        self.job_id = job_id
        self.category = category
        self.person_bytes = person_bytes
        self.garment_bytes = garment_bytes
        self.person_filename = person_filename
        self.garment_filename = garment_filename
        self.prompt = prompt
        self.status = "queued" # queued, validating, processing, completed, failed, cancelled
        self.created_at = time.time()
        self.updated_at = time.time()
        self.progress = 0
        self.result: Optional[TryOnResult] = None
        self.error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        output_url = self.result.output_url if self.result else None
        return {
            "job_id": self.job_id,
            "jobId": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "category": self.category,
            "prompt": self.prompt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result.to_dict() if self.result else None,
            "resultUrl": output_url,
            "output_url": output_url,
            "output_image_url": output_url,
            "error_message": self.error_message,
        }

class JobManager:
    def __init__(self, registry: ModelRegistry, output_dir: str):
        self.registry = registry
        self.output_dir = output_dir
        self.jobs: Dict[str, TryOnJob] = {}
        self.total_completed = 0
        self.total_failed = 0
        self.total_latency_ms = 0.0

    def create_job(
        self,
        category: str,
        person_bytes: bytes,
        garment_bytes: bytes,
        person_filename: str = "person.jpg",
        garment_filename: str = "garment.jpg",
        prompt: Optional[str] = None,
    ) -> TryOnJob:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = TryOnJob(
            job_id=job_id,
            category=category,
            person_bytes=person_bytes,
            garment_bytes=garment_bytes,
            person_filename=person_filename,
            garment_filename=garment_filename,
            prompt=prompt,
        )
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[TryOnJob]:
        return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in ["completed", "failed", "cancelled"]:
            return False
        job.status = "cancelled"
        job.updated_at = time.time()
        return True

    async def execute_job(self, job_id: str, model_name: Optional[str] = None):
        job = self.jobs.get(job_id)
        if not job or job.status == "cancelled":
            return

        adapter = self.registry.get_model(model_name)
        
        try:
            job.status = "validating"
            job.progress = 25
            job.updated_at = time.time()
            await asyncio.sleep(0.02)

            try:
                person_img = Image.open(io.BytesIO(job.person_bytes))
                garment_img = Image.open(io.BytesIO(job.garment_bytes))
            except Exception as e:
                job.status = "failed"
                job.error_message = f"Invalid image format: {str(e)}"
                job.updated_at = time.time()
                self.total_failed += 1
                return

            valid, err = adapter.validate_inputs(person_img, garment_img, job.category)
            if not valid:
                job.status = "failed"
                job.error_message = err
                job.updated_at = time.time()
                self.total_failed += 1
                return

            if job.status == "cancelled":
                return

            job.status = "processing"
            job.progress = 60
            job.updated_at = time.time()
            
            loop = asyncio.get_event_loop()
            try:
                # Use native async inference if supported (e.g. FalFluxVtoAdapter)
                if hasattr(adapter, "infer_async") and asyncio.iscoroutinefunction(adapter.infer_async):
                    result = await asyncio.wait_for(
                        adapter.infer_async(
                            person_img,
                            garment_img,
                            job.category,
                            job.job_id,
                            self.output_dir,
                            prompt=job.prompt
                        ),
                        timeout=90.0
                    )
                else:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            adapter.infer,
                            person_img,
                            garment_img,
                            job.category,
                            job.job_id,
                            self.output_dir
                        ),
                        timeout=90.0
                    )
            except asyncio.TimeoutError:
                job.status = "failed"
                job.error_message = "Inference execution timed out after 90s to prevent worker starvation."
                job.updated_at = time.time()
                self.total_failed += 1
                return

            if job.status == "cancelled":
                return

            job.status = "completed"
            job.progress = 100
            job.result = result
            job.updated_at = time.time()
            
            self.total_completed += 1
            self.total_latency_ms += result.latency_ms

        except Exception as e:
            job.status = "failed"
            job.error_message = f"Inference execution failed: {str(e)}"
            job.updated_at = time.time()
            self.total_failed += 1

    def get_metrics(self) -> Dict[str, Any]:
        avg_latency = (
            (self.total_latency_ms / self.total_completed)
            if self.total_completed > 0
            else 0.0
        )
        total_jobs = len(self.jobs)
        success_rate = (
            (self.total_completed / (self.total_completed + self.total_failed)) * 100
            if (self.total_completed + self.total_failed) > 0
            else 100.0
        )
        return {
            "total_submitted_jobs": total_jobs,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "success_rate_percent": round(success_rate, 2),
            "average_latency_ms": round(avg_latency, 2),
            "active_queued_jobs": sum(1 for j in self.jobs.values() if j.status in ["queued", "validating", "processing"]),
        }
