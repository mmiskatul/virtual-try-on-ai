# AI Virtual Try-On Service (FastAPI)

Dedicated Python asynchronous AI service for garment synthesis, posture alignment, flow warping, and virtual try-on inference.

## Technology Stack
- Framework: [FastAPI](https://fastapi.tiangolo.com/)
- ASGI Server: [Uvicorn](https://www.uvicorn.org/)
- Python: >= 3.10
- Vision Libraries: Pillow, NumPy

## Standalone Execution

### 1. Install Dependencies & Configure Environment
```bash
pip install -r requirements.txt
cp .env.example .env
```

### 2. Run the Service
```bash
python main.py
# Server will run at http://localhost:8000
```

### 3. Run Automated Tests
```bash
python test_ai_service.py
```

## Key API Endpoints
- `GET /health`: Service health and active model capability checks
- `POST /api/v1/try-on/jobs`: Asynchronous try-on inference job submission
- `GET /api/v1/try-on/jobs/{job_id}`: Job status polling and result retrieval
- `GET /api/v1/models`: Model registry & active adapter capabilities
- `GET /api/v1/metrics`: Latency and job throughput telemetry
