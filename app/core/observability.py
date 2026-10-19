import os
import sys
import time
import json
import uuid
import logging
import psutil
from typing import Dict, Any, Optional, List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse, JSONResponse
from fastapi import APIRouter

SENSITIVE_KEYS = {
    'password', 'pass', 'pwd', 'secret', 'token', 'jwt',
    'authorization', 'auth', 'creditcard', 'card', 'cvv',
    'apikey', 'api_key', 'salt', 'hash', 'connectionstring'
}

def redact_sensitive_data(data: Any, depth: int = 0) -> Any:
    if depth > 5 or data is None:
        return data
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            lower_k = "".join(c for c in str(k).lower() if c.isalnum())
            if lower_k in SENSITIVE_KEYS:
                cleaned[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                cleaned[k] = redact_sensitive_data(v, depth + 1)
            else:
                cleaned[k] = v
        return cleaned
    elif isinstance(data, list):
        return [redact_sensitive_data(item, depth + 1) for item in data]
    return data

class AIMetricsRegistry:
    def __init__(self, service_name: str = "ai_service"):
        self.service_name = service_name
        self.start_time = time.time()
        self.in_flight_requests = 0
        self.requests_total: Dict[str, int] = {}
        self.latencies_ms: List[float] = []
        self.max_latencies_kept = 2000

    def record_request_start(self):
        self.in_flight_requests += 1

    def record_request_end(self, method: str, route: str, status_code: int, duration_ms: float):
        self.in_flight_requests = max(0, self.in_flight_requests - 1)
        status_group = f"{status_code // 100}xx"
        key = f'method="{method}",route="{route}",status="{status_code}",status_group="{status_group}"'
        self.requests_total[key] = self.requests_total.get(key, 0) + 1

        if len(self.latencies_ms) >= self.max_latencies_kept:
            self.latencies_ms.pop(0)
        self.latencies_ms.append(duration_ms)

    def get_percentiles(self) -> Dict[str, float]:
        if not self.latencies_ms:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "count": 0, "avg": 0.0}
        s = sorted(self.latencies_ms)
        n = len(s)
        p50 = s[int(n * 0.5)] if n > 0 else 0.0
        p90 = s[min(int(n * 0.9), n - 1)] if n > 0 else 0.0
        p95 = s[min(int(n * 0.95), n - 1)] if n > 0 else 0.0
        p99 = s[min(int(n * 0.99), n - 1)] if n > 0 else 0.0
        avg = round(sum(s) / n, 2)
        return {
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "count": n,
            "avg": avg
        }

    def to_prometheus_format(self, job_manager=None) -> str:
        prefix = self.service_name.replace("-", "_")
        proc = psutil.Process()
        mem = proc.memory_info()
        cpu = proc.cpu_times()
        uptime = int(time.time() - self.start_time)
        percentiles = self.get_percentiles()

        lines = [
            f"# HELP {prefix}_uptime_seconds Process uptime in seconds",
            f"# TYPE {prefix}_uptime_seconds gauge",
            f"{prefix}_uptime_seconds {uptime}",
            "",
            f"# HELP {prefix}_process_memory_bytes Process memory footprint",
            f"# TYPE {prefix}_process_memory_bytes gauge",
            f'{prefix}_process_memory_bytes{{type="rss"}} {mem.rss}',
            f'{prefix}_process_memory_bytes{{type="vms"}} {mem.vms}',
            "",
            f"# HELP {prefix}_cpu_seconds_total Total user and system CPU time in seconds",
            f"# TYPE {prefix}_cpu_seconds_total counter",
            f'{prefix}_cpu_seconds_total{{type="user"}} {cpu.user}',
            f'{prefix}_cpu_seconds_total{{type="system"}} {cpu.system}',
            "",
            f"# HELP {prefix}_http_in_flight_requests Currently processing HTTP requests",
            f"# TYPE {prefix}_http_in_flight_requests gauge",
            f"{prefix}_http_in_flight_requests {self.in_flight_requests}",
            "",
            f"# HELP {prefix}_http_requests_total Total HTTP requests handled",
            f"# TYPE {prefix}_http_requests_total counter"
        ]

        if not self.requests_total:
            lines.append(f'{prefix}_http_requests_total{{status="none"}} 0')
        else:
            for labels, count in self.requests_total.items():
                lines.append(f"{prefix}_http_requests_total{{{labels}}} {count}")

        lines.extend([
            "",
            f"# HELP {prefix}_http_request_duration_ms Latency percentiles in milliseconds",
            f"# TYPE {prefix}_http_request_duration_ms summary",
            f'{prefix}_http_request_duration_ms{{quantile="0.5"}} {percentiles["p50"]}',
            f'{prefix}_http_request_duration_ms{{quantile="0.9"}} {percentiles["p90"]}',
            f'{prefix}_http_request_duration_ms{{quantile="0.95"}} {percentiles["p95"]}',
            f'{prefix}_http_request_duration_ms{{quantile="0.99"}} {percentiles["p99"]}',
            f'{prefix}_http_request_duration_ms_sum {round(percentiles["avg"] * percentiles["count"], 2)}',
            f'{prefix}_http_request_duration_ms_count {percentiles["count"]}',
            ""
        ])

        if job_manager:
            try:
                metrics = job_manager.get_metrics()
                lines.extend([
                    f"# HELP {prefix}_tryon_jobs_total Total virtual try-on jobs submitted",
                    f"# TYPE {prefix}_tryon_jobs_total counter",
                    f"{prefix}_tryon_jobs_total {metrics.get('total_submitted_jobs', 0)}",
                    "",
                    f"# HELP {prefix}_tryon_jobs_completed_total Virtual try-on jobs completed successfully",
                    f"# TYPE {prefix}_tryon_jobs_completed_total counter",
                    f"{prefix}_tryon_jobs_completed_total {metrics.get('total_completed', 0)}",
                    "",
                    f"# HELP {prefix}_tryon_jobs_failed_total Virtual try-on jobs failed",
                    f"# TYPE {prefix}_tryon_jobs_failed_total counter",
                    f"{prefix}_tryon_jobs_failed_total {metrics.get('total_failed', 0)}",
                    "",
                    f"# HELP {prefix}_tryon_active_queued_jobs Virtual try-on jobs waiting in queue",
                    f"# TYPE {prefix}_tryon_active_queued_jobs gauge",
                    f"{prefix}_tryon_active_queued_jobs {metrics.get('active_queued_jobs', 0)}",
                    ""
                ])
            except Exception:
                pass

        return "\n".join(lines) + "\n"

    def to_json(self, job_manager=None) -> Dict[str, Any]:
        proc = psutil.Process()
        mem = proc.memory_info()
        data = {
            "service": self.service_name,
            "uptime_seconds": int(time.time() - self.start_time),
            "memory": {
                "rss_mb": round(mem.rss / (1024 * 1024), 2),
                "vms_mb": round(mem.vms / (1024 * 1024), 2)
            },
            "latencies_ms": self.get_percentiles(),
            "in_flight_requests": self.in_flight_requests
        }
        if job_manager:
            try:
                data["tryon_engine"] = job_manager.get_metrics()
            except Exception:
                pass
        return data

class StructuredLogger:
    def __init__(self, service_name: str = "ai-service"):
        self.service_name = service_name

    def log(self, level: str, request_id: str, message: str, extra: Optional[Dict[str, Any]] = None):
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "service": self.service_name,
            "level": level.lower(),
            "requestId": request_id,
            "message": message
        }
        if extra:
            entry["extra"] = redact_sensitive_data(extra)
        
        # In test mode, suppress noisy 2xx info logs
        is_test = os.environ.get("NODE_ENV") == "test" or os.environ.get("ENV") == "test"
        if is_test and level == "info" and extra and extra.get("statusCode", 200) < 400:
            return

        serialized = json.dumps(entry)
        if level == "error":
            sys.stderr.write(serialized + "\n")
            sys.stderr.flush()
        else:
            sys.stdout.write(serialized + "\n")
            sys.stdout.flush()

    def info(self, message: str, request_id: str = "system", extra: Optional[Dict[str, Any]] = None):
        self.log("info", request_id, message, extra)

    def warn(self, message: str, request_id: str = "system", extra: Optional[Dict[str, Any]] = None):
        self.log("warn", request_id, message, extra)

    def error(self, message: str, request_id: str = "system", extra: Optional[Dict[str, Any]] = None):
        self.log("error", request_id, message, extra)

ai_metrics = AIMetricsRegistry("ai-service")
ai_logger = StructuredLogger("ai-service")

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        raw_req_id = request.headers.get("x-request-id")
        request_id = raw_req_id if raw_req_id else f"req-{uuid.uuid4().hex[:16]}"

        traceparent = request.headers.get("traceparent")
        trace_id = ""
        span_id = ""
        if traceparent and traceparent.startswith("00-"):
            parts = traceparent.split("-")
            if len(parts) >= 4:
                trace_id = parts[1]
                span_id = parts[2]
        if not trace_id:
            trace_id = uuid.uuid4().hex
            span_id = uuid.uuid4().hex[:16]

        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request.state.span_id = span_id

        ai_metrics.record_request_start()
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            route = request.url.path
            ai_metrics.record_request_end(request.method, route, 500, duration_ms)
            ai_logger.error(
                f"{request.method} {request.url.path} -> 500 Uncaught Exception ({duration_ms}ms)",
                request_id=request_id,
                extra={
                    "method": request.method,
                    "url": str(request.url),
                    "statusCode": 500,
                    "durationMs": duration_ms,
                    "error": str(exc),
                    "traceId": trace_id,
                    "spanId": span_id
                }
            )
            raise exc

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        route = request.url.path
        ai_metrics.record_request_end(request.method, route, response.status_code, duration_ms)

        response.headers["x-request-id"] = request_id
        response.headers["traceparent"] = f"00-{trace_id}-{span_id}-01"

        level = "error" if response.status_code >= 500 else ("warn" if response.status_code >= 400 else "info")
        ai_logger.log(
            level=level,
            request_id=request_id,
            message=f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)",
            extra={
                "method": request.method,
                "url": str(request.url),
                "statusCode": response.status_code,
                "durationMs": duration_ms,
                "traceId": trace_id,
                "spanId": span_id
            }
        )

        return response

def create_observability_router(registry=None, job_manager=None, output_dir: Optional[str] = None) -> APIRouter:
    r = APIRouter(tags=["Observability"])

    @r.get("/live")
    async def liveness():
        return {
            "status": "alive",
            "service": "ai-service",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

    @r.get("/ready")
    async def readiness():
        proc = psutil.Process()
        mem_mb = proc.memory_info().rss / (1024 * 1024)
        mem_ok = mem_mb < 2048.0  # Under 2GB threshold

        models_count = len(registry.list_models()) if registry else 0
        models_ok = models_count > 0

        storage_ok = True
        if output_dir:
            try:
                os.makedirs(output_dir, exist_ok=True)
                test_file = os.path.join(output_dir, ".health_probe")
                with open(test_file, "w") as f:
                    f.write("probe")
                os.remove(test_file)
            except Exception:
                storage_ok = False

        is_ready = mem_ok and models_ok and storage_ok
        payload = {
            "status": "ready" if is_ready else "unready",
            "service": "ai-service",
            "checks": {
                "memory": "ok" if mem_ok else "exhausted",
                "models": "ok" if models_ok else "no_models_loaded",
                "storage": "ok" if storage_ok else "unwritable"
            },
            "details": {
                "memory_rss_mb": round(mem_mb, 2),
                "available_models": models_count
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

        if not is_ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    @r.get("/metrics")
    async def metrics():
        body = ai_metrics.to_prometheus_format(job_manager)
        return PlainTextResponse(
            content=body,
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    @r.get("/metrics/json")
    async def metrics_json():
        return ai_metrics.to_json(job_manager)

    return r
