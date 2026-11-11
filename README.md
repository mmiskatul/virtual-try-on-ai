# AI Virtual Try-On Service (`ai-service`)

Separately deployable **Python 3.11+ / FastAPI / PyTorch** Virtual Try-On AI Inference & Worker service powering asynchronous and internal VTON execution across the multi-tenant SaaS ecosystem.

## Architecture Overview

- **Model Plug-in Contract ([`app/adapters/model_contract.py`](./app/adapters/model_contract.py))**:
  - `TryOnModel` Abstract Base Class (`preprocess`, `infer`, `postprocess`) + `AdapterTryOnModelBridge`.
  - Pluggable adapters (`gemini`, `fal`, `viton_hd` / deterministic preview fallback) registered in [`app/adapters/registry.py`](./app/adapters/registry.py).
- **Private Object Storage Adapter ([`app/services/storage_adapter.py`](./app/services/storage_adapter.py))**:
  - Reads `customer-uploads` and `brand-assets`, writes `generated-results` either via Supabase Storage REST (`SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`) or private volume buckets (`PRIVATE_OBJECT_ROOT`), rejecting any path traversal sequences (`..`).
- **Execution Pipeline ([`app/services/pipeline.py`](./app/services/pipeline.py))**:
  - `TryOnPipeline.process_event(TryOnGenerationRequestedV1)` validates inputs, runs `preprocess -> infer -> postprocess`, stores outputs privately in `generated-results`, and emits typed `TryOnGenerationCompletedV1` or `TryOnGenerationFailedV1` events.
- **RabbitMQ Worker ([`worker.py`](./worker.py) & [`app/services/rabbitmq_worker.py`](./app/services/rabbitmq_worker.py))**:
  - Consumes `tryon.generation.requests` (`prefetch=1`) via `aio-pika` and publishes `tryon.generation.completed` / `tryon.generation.failed` back to `vton.events`.
- **Internal Service API ([`app/api/routes/internal.py`](./app/api/routes/internal.py))**:
  - `GET /internal/v1/worker/health`
  - `POST /internal/v1/events/ping`
  - `POST /internal/v1/try-on/execute`
  - All `/internal/v1/*` routes require `X-Service-Key` matching `INTERNAL_SERVICE_KEY` (timing-safe comparison).

## Running & Testing

```bash
# Start HTTP API server
python -m uvicorn app:create_app --factory --host 0.0.0.0 --port 8000

# Start RabbitMQ AI worker process
python worker.py

# Run test suite
ENV=test python -m pytest tests/
```
