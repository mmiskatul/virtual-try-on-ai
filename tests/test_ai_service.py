"""
Integration & Unit Test for AI Service Model Adapters and Asynchronous Job Queue
"""
import asyncio
import io
import os
import sys
from PIL import Image, ImageDraw

# Add parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.adapters.registry import ModelRegistry
from app.services.job_queue import JobManager
from app.core.config import settings

def create_dummy_images():
    person = Image.new("RGB", (300, 400), color=(235, 215, 200))
    draw = ImageDraw.Draw(person)
    draw.ellipse((120, 20, 180, 80), fill=(210, 180, 160))
    draw.rectangle((100, 85, 200, 260), fill=(220, 195, 175))
    draw.rectangle((110, 260, 145, 390), fill=(80, 80, 90))
    draw.rectangle((155, 260, 190, 390), fill=(80, 80, 90))

    garment = Image.new("RGBA", (200, 200), color=(0, 0, 0, 0))
    g_draw = ImageDraw.Draw(garment)
    g_draw.polygon([(40, 20), (160, 20), (190, 70), (160, 90), (150, 60), (150, 180), (50, 180), (50, 60), (40, 90), (10, 70)], fill=(16, 185, 129, 255))

    p_bytes = io.BytesIO()
    person.save(p_bytes, format="JPEG")
    
    g_bytes = io.BytesIO()
    garment.save(g_bytes, format="PNG")

    return p_bytes.getvalue(), g_bytes.getvalue()

async def run_tests():
    print("[TEST] Initializing Model Registry...")
    registry = ModelRegistry()
    models = registry.list_models()
    assert len(models) >= 1, "Expected at least 1 registered model"
    print(f"[PASS] Model registered: {models[0]['name']} (v{models[0]['version']})")

    job_mgr = JobManager(registry, settings.output_dir)
    p_bytes, g_bytes = create_dummy_images()

    print("[TEST] Creating Try-On Job...")
    job = job_mgr.create_job(
        category="tops",
        person_bytes=p_bytes,
        garment_bytes=g_bytes,
        person_filename="person_test.jpg",
        garment_filename="garment_test.png"
    )
    assert job.status == "queued", f"Expected 'queued', got {job.status}"
    print(f"[PASS] Job created: {job.job_id}")

    print("[TEST] Executing Job Asynchronously...")
    await job_mgr.execute_job(job.job_id)
    
    completed_job = job_mgr.get_job(job.job_id)
    assert completed_job.status == "completed", f"Job failed with: {completed_job.error_message}"
    assert completed_job.result is not None
    assert os.path.exists(completed_job.result.output_image_path), "Output image file does not exist!"
    
    print(f"[PASS] Job completed in {completed_job.result.latency_ms:.2f}ms")
    print(f"[PASS] Generated try-on output: {completed_job.result.output_image_path}")

    metrics = job_mgr.get_metrics()
    assert metrics["total_completed"] == 1
    assert metrics["success_rate_percent"] == 100.0
    print(f"[PASS] AI Service Metrics: {metrics}")
    print("\nALL AI-SERVICE TESTS PASSED SUCCESSFULLY! (100% OK)")

if __name__ == "__main__":
    asyncio.run(run_tests())
