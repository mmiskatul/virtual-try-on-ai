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

    # Boundary Input Validation & Sanitization Tests (HTTP Boundary)
    from fastapi.testclient import TestClient
    from app import create_app

    print("\n[TEST] Initializing FastAPI TestClient for Boundary Security Tests...")
    fastapi_app = create_app()
    client = TestClient(fastapi_app)

    # Test HTTP Health Check
    health_res = client.get("/health")
    assert health_res.status_code == 200, f"Expected 200, got {health_res.status_code}"
    print("[PASS] HTTP Test 1: Service Health Check OK")

    # Test Boundary SQLi in Query Parameter
    sqli_q_res = client.get("/api/v1/models?sort=' OR '1'='1")
    assert sqli_q_res.status_code == 400
    sqli_q_data = sqli_q_res.json()
    assert sqli_q_data["code"] == "INJECTION_ATTACK_DETECTED_SQLI"
    print("[PASS] HTTP Test 2: Boundary SQLi Rejection in Query Parameter OK")

    # Test Boundary XSS in Route Path Parameter
    xss_p_res = client.get("/api/v1/try-on/jobs/<script>alert(1)</script>")
    assert xss_p_res.status_code == 400
    xss_p_data = xss_p_res.json()
    assert xss_p_data["code"] == "INJECTION_ATTACK_DETECTED_XSS"
    print("[PASS] HTTP Test 3: Boundary XSS Rejection in Route Path Parameter OK")

    # Test Boundary SQLi in HTTP Headers
    sqli_h_res = client.get("/health", headers={"x-tracking-ref": "UNION SELECT * FROM users --"})
    assert sqli_h_res.status_code == 400
    sqli_h_data = sqli_h_res.json()
    assert sqli_h_data["code"] == "INJECTION_ATTACK_DETECTED_SQLI"
    print("[PASS] HTTP Test 4: Boundary SQLi Rejection in HTTP Headers OK")

    # Test Boundary Null Byte in HTTP Headers
    null_h_res = client.get("/health", headers={"x-custom-ref": "header\0byte"})
    assert null_h_res.status_code == 400
    null_h_data = null_h_res.json()
    assert null_h_data["code"] == "INJECTION_ATTACK_DETECTED_NULL_BYTE"
    print("[PASS] HTTP Test 5: Boundary Null Byte Rejection in HTTP Headers OK")

    # Test Boundary SQLi in Multipart Form Field
    p_data, g_data = create_dummy_images()
    sqli_form_res = client.post(
        "/api/v1/try-on/jobs",
        data={"category": "tops' OR 1=1 --"},
        files={
            "person_image": ("person.jpg", p_data, "image/jpeg"),
            "garment_image": ("garment.png", g_data, "image/png"),
        }
    )
    assert sqli_form_res.status_code == 400
    sqli_form_data = sqli_form_res.json()
    assert sqli_form_data["detail"]["code"] == "INJECTION_ATTACK_DETECTED_SQLI"
    print("[PASS] HTTP Test 6: Boundary SQLi Rejection in Multipart Form Data OK")

    # Test Boundary Path Traversal in Uploaded Filename
    traversal_form_res = client.post(
        "/api/v1/try-on/jobs",
        data={"category": "tops"},
        files={
            "person_image": ("../../secret_photo.jpg", p_data, "image/jpeg"),
            "garment_image": ("garment.png", g_data, "image/png"),
        }
    )
    assert traversal_form_res.status_code == 400
    traversal_form_data = traversal_form_res.json()
    assert traversal_form_data["detail"]["code"] == "INJECTION_ATTACK_DETECTED_PATH_TRAVERSAL"
    print("[PASS] HTTP Test 7: Boundary Path Traversal Rejection in Filename OK")

    print("\nALL AI-SERVICE TESTS (CORE + BOUNDARY SECURITY) PASSED SUCCESSFULLY! (100% OK)")

if __name__ == "__main__":
    asyncio.run(run_tests())
