"""
Integration & Unit Test for AI Service Model Adapters and Asynchronous Job Queue
"""
import asyncio
import io
import os
import sys
import time
import base64
import secrets
import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("ENV", "test")
os.environ.setdefault("ALLOW_UNAUTHENTICATED_DEV", "true")  # the existing suite exercises the engine without a key
os.environ.setdefault("TEST_CRASH_MARKER", f"crash-test-{secrets.token_hex(8)}")


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
    client = TestClient(fastapi_app, raise_server_exceptions=False)

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

    # Test HTTP Test 8: Strict CORS Allowed Origin Preflight
    cors_allow_res = client.options(
        "/api/v1/models",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "GET",
        }
    )
    assert cors_allow_res.status_code == 200
    assert cors_allow_res.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert cors_allow_res.headers.get("access-control-allow-credentials") == "true"
    print("[PASS] HTTP Test 8: Strict CORS Allowed Origin OK")

    # Test HTTP Test 9: Strict CORS Disallowed Origin Preflight
    cors_block_res = client.options(
        "/api/v1/models",
        headers={
            "origin": "https://attacker-origin.evil",
            "access-control-request-method": "GET",
        }
    )
    assert cors_block_res.headers.get("access-control-allow-origin") is None
    print("[PASS] HTTP Test 9: Strict CORS Disallowed Origin Blocked OK")

    # Test HTTP Test 10: Rate Limiting Response Headers & Burst Exhaustion
    models_res = client.get("/api/v1/models")
    assert models_res.status_code == 200
    assert "x-ratelimit-limit" in models_res.headers
    assert "x-ratelimit-remaining" in models_res.headers
    assert "x-ratelimit-reset" in models_res.headers

    # Exhaust sensitive try-on rate limit using dedicated IP
    test_burst_ip = "198.51.100.123"
    hit_429 = False
    for _ in range(25):
        r = client.post(
            "/api/v1/try-on/jobs",
            data={"category": "tops"},
            files={
                "person_image": ("p.jpg", p_data, "image/jpeg"),
                "garment_image": ("g.png", g_data, "image/png"),
            },
            headers={"x-forwarded-for": test_burst_ip}
        )
        if r.status_code == 429:
            hit_429 = True
            r_json = r.json()
            assert r_json["code"] == "RATE_LIMIT_EXCEEDED"
            assert "retry_after" in r_json
            assert "retry-after" in r.headers
            break

    assert hit_429, "Rate limit burst must return HTTP 429"
    print("[PASS] HTTP Test 10: Rate Limiting Headers & DDoS Protection (HTTP 429) Enforced OK")

    # HTTP Test 11: Graceful Exception Handling & Zero Secret/Traceback Leakage
    crash_res = client.get("/test/crash")
    assert crash_res.status_code == 500, f"Expected 500, got {crash_res.status_code}"
    crash_data = crash_res.json()
    assert crash_data["error"] == "InternalServerError"
    assert crash_data["code"] == "INTERNAL_SERVER_ERROR"
    assert "errorId" in crash_data, "Expected errorId in response"
    assert os.environ["TEST_CRASH_MARKER"] not in crash_res.text, "Secret key must NEVER leak to client"
    assert "Traceback" not in crash_res.text, "Traceback must NEVER leak to client"
    print("[PASS] HTTP Test 11: Graceful Exception Handling (Zero Secret/Traceback Leakage) OK")

    # HTTP Test 12: Structured 404 Not Found Routing
    not_found_res = client.get("/api/v1/invalid-route-path-xyz")
    assert not_found_res.status_code == 404, f"Expected 404, got {not_found_res.status_code}"
    not_found_data = not_found_res.json()
    assert not_found_data["error"] == "NotFoundError"
    assert not_found_data["code"] == "ROUTE_NOT_FOUND"
    print("[PASS] HTTP Test 12: Structured 404 Not Found Routing OK")

    # HTTP Test 13: Idempotent Try-On Job Submission
    ai_idemp_key = f"ai_idemp_{int(time.time()*1000)}"
    idemp_post1 = client.post(
        "/api/v1/try-on/jobs",
        data={"category": "tops"},
        files={
            "person_image": ("person.jpg", p_bytes, "image/jpeg"),
            "garment_image": ("garment.png", g_bytes, "image/png"),
        },
        headers={"idempotency-key": ai_idemp_key}
    )
    assert idemp_post1.status_code == 200, f"Expected 200, got {idemp_post1.status_code}"
    job_data_1 = idemp_post1.json()
    assert "job_id" in job_data_1

    # Retry duplicate request with identical idempotency key
    idemp_post2 = client.post(
        "/api/v1/try-on/jobs",
        data={"category": "tops"},
        files={
            "person_image": ("person.jpg", p_bytes, "image/jpeg"),
            "garment_image": ("garment.png", g_bytes, "image/png"),
        },
        headers={"idempotency-key": ai_idemp_key}
    )
    assert idemp_post2.status_code == 200
    assert idemp_post2.headers.get("idempotency-replay") == "true"
    job_data_2 = idemp_post2.json()
    assert job_data_2["job_id"] == job_data_1["job_id"], "Must return identical job ID on replay"
    print("[PASS] HTTP Test 13: Idempotent Try-On Job Submission & Replay OK")

    # HTTP Test 14: Idempotency Payload Mismatch Rejection (HTTP 422)
    idemp_mismatch = client.post(
        "/api/v1/try-on/jobs",
        data={"category": "dresses"}, # Changed category!
        files={
            "person_image": ("person.jpg", p_bytes, "image/jpeg"),
            "garment_image": ("garment.png", g_bytes, "image/png"),
        },
        headers={"idempotency-key": ai_idemp_key}
    )
    assert idemp_mismatch.status_code == 422, f"Expected 422, got {idemp_mismatch.status_code}"
    mismatch_data = idemp_mismatch.json()
    assert mismatch_data["detail"]["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    print("[PASS] HTTP Test 14: Idempotency Payload Mismatch Rejection (HTTP 422) OK")

    # HTTP Test 15: Infrastructure Liveness Probe (/live)
    live_res = client.get("/live")
    assert live_res.status_code == 200, f"Expected 200, got {live_res.status_code}"
    live_data = live_res.json()
    assert live_data["status"] == "alive"
    assert live_data["service"] == "ai-service"
    print("[PASS] HTTP Test 15: Infrastructure Liveness Probe (/live) OK")

    # HTTP Test 16: Deep Readiness Probe (/ready)
    ready_res = client.get("/ready")
    assert ready_res.status_code == 200, f"Expected 200, got {ready_res.status_code}"
    ready_data = ready_res.json()
    assert ready_data["status"] == "ready"
    assert ready_data["checks"]["memory"] == "ok"
    assert ready_data["checks"]["models"] == "ok"
    assert ready_data["checks"]["storage"] == "ok"
    assert ready_data["details"]["available_models"] >= 1
    print("[PASS] HTTP Test 16: Deep Readiness Probe (/ready) OK")

    # HTTP Test 17: Prometheus Standard Metrics Exposition (/metrics)
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200, f"Expected 200, got {metrics_res.status_code}"
    assert "text/plain" in metrics_res.headers.get("content-type", "")
    metrics_text = metrics_res.text
    assert "# HELP ai_service_uptime_seconds" in metrics_text
    assert "# HELP ai_service_process_memory_bytes" in metrics_text
    assert "ai_service_http_requests_total" in metrics_text
    assert "ai_service_tryon_jobs_total" in metrics_text
    print("[PASS] HTTP Test 17: Prometheus Standard Metrics Exposition (/metrics) OK")

    # HTTP Test 18: JSON Metrics Summary Endpoint (/metrics/json)
    json_metrics_res = client.get("/metrics/json")
    assert json_metrics_res.status_code == 200
    json_metrics = json_metrics_res.json()
    assert json_metrics["service"] == "ai-service"
    assert "memory" in json_metrics
    assert "latencies_ms" in json_metrics
    assert "tryon_engine" in json_metrics
    print("[PASS] HTTP Test 18: JSON Metrics Summary Endpoint (/metrics/json) OK")

    # HTTP Test 19: Request Correlation ID & OpenTelemetry Tracing Headers
    custom_trace_id = "req-ai-custom-trace-777"
    traced_res = client.get("/live", headers={"x-request-id": custom_trace_id})
    assert traced_res.status_code == 200
    assert traced_res.headers.get("x-request-id") == custom_trace_id
    assert "traceparent" in traced_res.headers, "Must attach W3C traceparent header"
    print("[PASS] HTTP Test 19: Request Correlation ID & OpenTelemetry Tracing OK")

    # HTTP Test 20: Sensitive Data Redaction in Structured Logging
    from app.core.observability import redact_sensitive_data
    dirty_event = {
        "userId": "user_123",
        "password": "GpuSuperSecretPassword99!",
        "token": "bearer.token.ai.cluster",
        "nested": {
            "apiKey": "sk_live_ai_engine_secret",
            "model": "VITON-HD"
        }
    }
    scrubbed = redact_sensitive_data(dirty_event)
    assert scrubbed["userId"] == "user_123"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["token"] == "[REDACTED]"
    assert scrubbed["nested"]["apiKey"] == "[REDACTED]"
    assert scrubbed["nested"]["model"] == "VITON-HD"
    print("[PASS] HTTP Test 20: Structured Log Sensitive Data Redaction Verified OK")

    # HTTP Test 21: Cloudinary Storage Readiness & Storage Status Endpoint
    storage_res = client.get("/api/v1/storage/status")
    assert storage_res.status_code == 200
    storage_data = storage_res.json()
    assert "provider" in storage_data
    assert storage_data.get("storage_delegated_to_backend") is True
    assert storage_data["status"] == "ready"
    print("[PASS] HTTP Test 21: Cloudinary Storage Adapter & Status Verification OK")

    # HTTP Test 22: JSON Payload Try-On Submission & Base64 Data URI Support
    json_post = client.post(
        "/api/v1/try-on/jobs",
        json={
            "personImage": "data:image/jpeg;base64," + base64.b64encode(p_bytes).decode("utf-8"),
            "garmentImage": "data:image/png;base64," + base64.b64encode(g_bytes).decode("utf-8"),
            "category": "tops"
        }
    )
    assert json_post.status_code == 200, f"Expected 200 for JSON try-on, got {json_post.status_code}"
    json_res_data = json_post.json()
    assert "job_id" in json_res_data
    assert json_res_data["status"] in ("queued", "processing", "completed")
    print("[PASS] HTTP Test 22: JSON Payload Try-On Submission & Base64 Data URI Support OK")

    # HTTP Test 23: Direct JSON Route Aliasing (/api/v1/tryon/jobs)
    alias_post = client.post(
        "/api/v1/tryon/jobs",
        json={
            "user_image_url": "data:image/jpeg;base64," + base64.b64encode(p_bytes).decode("utf-8"),
            "garment_image_url": "data:image/png;base64," + base64.b64encode(g_bytes).decode("utf-8"),
            "clothType": "tops"
        }
    )
    assert alias_post.status_code == 200, f"Expected 200 for alias tryon jobs, got {alias_post.status_code}"
    assert "job_id" in alias_post.json()
    print("[PASS] HTTP Test 23: Direct JSON Route Aliasing (/api/v1/tryon/jobs) OK")

    print("\nALL AI-SERVICE TESTS (CORE + BOUNDARY SECURITY + CORS + RATE LIMITING + RESILIENCE + IDEMPOTENCY + OBSERVABILITY + CLOUDINARY) PASSED SUCCESSFULLY! (100% OK)")

@pytest.mark.asyncio
async def test_full_ai_service_suite():
    await run_tests()

if __name__ == "__main__":
    asyncio.run(run_tests())


