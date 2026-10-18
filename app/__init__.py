import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.sanitizer import InputSanitizerMiddleware
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

    app.add_middleware(InputSanitizerMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Core singletons
    registry = ModelRegistry()
    job_manager = JobManager(registry=registry, output_dir=settings.output_dir)

    # Static file serving for generated results
    static_dir = os.path.join(settings.base_dir, "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Wire modular routers
    app.include_router(create_health_router(registry))
    app.include_router(create_models_router(registry))
    app.include_router(create_try_on_router(job_manager))
    app.include_router(create_metrics_router(job_manager))

    return app
