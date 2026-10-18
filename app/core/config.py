import os
from pydantic import BaseModel

# Automatically load .env if present
env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
if os.path.exists(env_file):
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())
    except Exception:
        pass

class Settings(BaseModel):
    title: str = "Multi-Tenant AI Virtual Try-On Engine"
    description: str = "High-performance asynchronous AI service for garment synthesis, person parsing, and virtual try-on pipelines."
    version: str = "1.0.0"
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    env: str = os.getenv("ENV", "development")
    base_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir: str = os.path.join(base_dir, "static", "results")
    max_upload_size_bytes: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10")) * 1024 * 1024

settings = Settings()
os.makedirs(settings.output_dir, exist_ok=True)
