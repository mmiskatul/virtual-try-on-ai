import os
from typing import Optional
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

from .vault import secrets_vault

class Settings(BaseModel):
    title: str = "Multi-Tenant AI Virtual Try-On Engine"
    description: str = "High-performance asynchronous AI service for garment synthesis, person parsing, and virtual try-on pipelines."
    version: str = "1.0.0"
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    server_url: str = os.getenv("SERVER_URL", f"http://localhost:{os.getenv('PORT', '8000')}")
    env: str = os.getenv("ENV", "development")
    api_key: str = secrets_vault.get_secret(
        name="AI_SERVICE_API_KEY",
        description="AI Service external client authentication key",
        required_in_production=True,
        min_length=24,
        development_fallback="vton_ai_service_api_key_dev_2026",
    )
    internal_service_key: str = secrets_vault.get_secret(
        name="INTERNAL_SERVICE_KEY",
        description="Internal backend-to-backend token",
        required_in_production=True,
        min_length=24,
        development_fallback="vton_internal_service_key_dev",
    )
    base_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir: str = os.path.join(base_dir, "static", "results")
    max_upload_size_bytes: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10")) * 1024 * 1024

    # Cloudinary Image Storage
    cloudinary_url: Optional[str] = os.getenv("CLOUDINARY_URL")
    cloudinary_cloud_name: Optional[str] = os.getenv("CLOUDINARY_CLOUD_NAME")
    cloudinary_api_key: Optional[str] = os.getenv("CLOUDINARY_API_KEY")
    cloudinary_api_secret: Optional[str] = os.getenv("CLOUDINARY_API_SECRET")
    cloudinary_folder: str = os.getenv("CLOUDINARY_FOLDER", "virtual-try-on/results")

    # External AI Virtual Try-On API (Cloud Provider: Fal.ai, Fashn.ai, Replicate, Kling, Segmind, or custom)
    fal_key: Optional[str] = os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY")
    vton_api_key: Optional[str] = os.getenv("VTON_API_KEY") or os.getenv("FAL_KEY") or os.getenv("FASHN_API_KEY") or os.getenv("REPLICATE_API_TOKEN") or os.getenv("KLING_API_KEY")
    vton_api_url: Optional[str] = os.getenv("VTON_API_URL")
    vton_provider: str = os.getenv("VTON_PROVIDER", "auto")

    # Google Gemini AI Multimodal Vision & Fashion Synthesis Orchestration
    gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

settings = Settings()
if settings.fal_key:
    os.environ["FAL_KEY"] = settings.fal_key
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
os.makedirs(settings.output_dir, exist_ok=True)
