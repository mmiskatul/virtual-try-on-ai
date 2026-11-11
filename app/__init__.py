import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.sanitizer import InputSanitizerMiddleware
from .core.rate_limiter import RateLimiterMiddleware
from .core.cors_config import CORS_ORIGIN_REGEX, ALLOWED_METHODS, ALLOWED_HEADERS, EXPOSED_HEADERS, get_explicit_origins
from .core.error_handler import setup_exception_handlers
from .core.observability import ObservabilityMiddleware, create_observability_router
from .adapters.registry import ModelRegistry
from .services.job_queue import JobManager
from .api.routes.health import create_health_router
from .api.routes.models import create_models_router
from .api.routes.try_on import create_try_on_router
from .api.routes.metrics import create_metrics_router

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.title,
        description=settings.description,
        version=settings.version,
    )

    # Centralized graceful error handling & 404 routing
    setup_exception_handlers(app)

    # 1. Application-level Sliding-Window Rate Limiting Middleware
    app.add_middleware(RateLimiterMiddleware)

    # 2. Boundary Input Validation & Sanitization Middleware
    app.add_middleware(InputSanitizerMiddleware)

    # 3. Strict CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_explicit_origins(),
        allow_origin_regex=CORS_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
        expose_headers=EXPOSED_HEADERS,
        max_age=86400,
    )

    # 4. Enterprise Observability Middleware (Request Correlation, Tracing, Metrics, JSON Logging)
    app.add_middleware(ObservabilityMiddleware)

    # Core singletons
    registry = ModelRegistry()
    job_manager = JobManager(registry=registry, output_dir=settings.output_dir)

    # Static file serving for generated results
    static_dir = os.path.join(settings.base_dir, "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Wire modular routers
    app.include_router(create_observability_router(registry=registry, job_manager=job_manager, output_dir=settings.output_dir))
    app.include_router(create_health_router(registry))
    app.include_router(create_models_router(registry))
    app.include_router(create_try_on_router(job_manager))
    app.include_router(create_metrics_router(job_manager))

    if settings.env in ("test", "development"):
        @app.get("/test/crash")
        async def test_crash():
            raise RuntimeError("Secret AI GPU cluster key in stack trace: aiGpuSecretToken9911")

    return app

