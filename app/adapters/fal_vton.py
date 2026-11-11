"""
Fal AI Virtual Try-On Adapter
Integrates fal-client to submit asynchronous virtual try-on requests to `fal-ai/flux-pro/v1/vto`.
Supports person photograph, garment product image, styling prompts, event streaming, and local caching.
"""

import os
import time
import asyncio
import logging
from typing import Dict, Any, Optional
from PIL import Image

try:
    import fal_client
    FAL_CLIENT_AVAILABLE = True
except ImportError:
    FAL_CLIENT_AVAILABLE = False

import httpx

from .base import BaseTryOnAdapter, TryOnResult
from ..core.config import settings

logger = logging.getLogger("ai_service.adapters.fal_vton")


class FalFluxVtoAdapter(BaseTryOnAdapter):
    """
    Adapter for Fal AI's FLUX Pro Virtual Try-On (`fal-ai/flux-pro/v1/vto`).
    Submits human image, garment image, and styling prompts to Fal AI cloud endpoint.
    """

    MODEL_ID = settings.fal_model  # from FAL_MODEL in .env

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.fal_key or settings.vton_api_key
        if self.api_key:
            os.environ["FAL_KEY"] = self.api_key

    @property
    def name(self) -> str:
        return "Fal-AI-Flux-VTO"

    @property
    def version(self) -> str:
        return "v1.0-flux-pro"

    @property
    def supported_categories(self) -> list[str]:
        return ["tops", "bottoms", "dresses", "outerwear"]

    def is_configured(self) -> bool:
        key = self.api_key or os.getenv("FAL_KEY") or os.getenv("FAL_API_KEY")
        return bool(key)

    def validate_inputs(self, person_img: Image.Image, garment_img: Image.Image, category: str) -> tuple[bool, Optional[str]]:
        if category.lower() not in self.supported_categories:
            return False, f"Unsupported category '{category}'. Supported: {self.supported_categories}"
        if not self.is_configured():
            return False, "Fal AI credentials not configured. Please set 'FAL_KEY' in ai-service/.env."
        return True, None

    def preprocess(self, person_img: Image.Image, garment_img: Image.Image) -> tuple[Image.Image, Image.Image]:
        return person_img, garment_img

    def default_prompt_for_category(self, category: str) -> str:
        cat = (category or "tops").lower()
        if "dress" in cat:
            return "A natural front-facing studio shot. The dress is worn naturally with realistic fabric drape."
        elif "bottom" in cat:
            return "A natural front-facing studio shot. The bottoms are worn naturally with a tailored fit."
        elif "outer" in cat or "coat" in cat or "jacket" in cat:
            return "A natural front-facing studio shot. The outerwear jacket is worn styled over the model."
        else:
            return "A natural front-facing studio shot. The garment is worn naturally."

    async def infer_async(
        self,
        person_img: Image.Image,
        garment_img: Image.Image,
        category: str,
        job_id: str,
        output_dir: str,
        prompt: Optional[str] = None
    ) -> TryOnResult:
        if not FAL_CLIENT_AVAILABLE:
            raise RuntimeError("fal_client is not installed. Please run: pip install fal-client")

        # Refresh key in env if updated
        current_key = self.api_key or os.getenv("FAL_KEY") or settings.fal_key or settings.vton_api_key
        if current_key:
            os.environ["FAL_KEY"] = current_key

        start_time = time.time()
        effective_prompt = prompt or self.default_prompt_for_category(category)

        logger.info(f"[Fal AI] Uploading input images for job '{job_id}'...")
        # 1. Upload human & garment images to Fal CDN storage
        try:
            human_image_url = await fal_client.upload_image_async(person_img)
            garment_image_url = await fal_client.upload_image_async(garment_img)
        except Exception as upload_err:
            logger.warning(f"[Fal AI] upload_image_async failed ({upload_err}), trying sync upload...")
            human_image_url = fal_client.upload_image(person_img)
            garment_image_url = fal_client.upload_image(garment_img)

        logger.info(f"[Fal AI] Submitting to {self.MODEL_ID} for job '{job_id}' with prompt: '{effective_prompt}'")

        # 2. Submit async request to fal-ai/flux-pro/v1/vto
        handler = await fal_client.submit_async(
            self.MODEL_ID,
            arguments={
                "prompt": effective_prompt,
                "human_image_url": human_image_url,
                "garment_image_url": garment_image_url
            },
        )

        async for event in handler.iter_events(with_logs=True):
            logger.info(f"[Fal AI] [{job_id}] {event}")

        result = await handler.get()
        logger.info(f"[Fal AI] Result received for job '{job_id}': {result}")

        # 3. Extract output image URL
        result_url = None
        if isinstance(result, dict):
            images = result.get("images")
            if isinstance(images, list) and len(images) > 0:
                first = images[0]
                result_url = first.get("url") if isinstance(first, dict) else str(first)
            elif "image" in result and isinstance(result["image"], dict):
                result_url = result["image"].get("url")
            elif "image_url" in result:
                result_url = result["image_url"]
            elif "output" in result:
                out = result["output"]
                result_url = out[0] if isinstance(out, list) and out else str(out)

        if not result_url:
            raise ValueError(f"No output image returned by Fal AI: {result}")

        # 4. Cache image locally to output_dir
        os.makedirs(output_dir, exist_ok=True)
        filename = f"tryon_{job_id}.jpg"
        filepath = os.path.join(output_dir, filename)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(result_url)
                if resp.status_code == 200:
                    with open(filepath, "wb") as f:
                        f.write(resp.content)
        except Exception as dl_err:
            logger.warning(f"[Fal AI] Could not download image locally for caching: {dl_err}")

        latency_ms = (time.time() - start_time) * 1000

        return TryOnResult(
            job_id=job_id,
            status="completed",
            output_image_path=filepath,
            output_url=result_url,
            latency_ms=latency_ms,
            model_name=self.name,
            model_version=self.version,
            metrics={
                "provider": "fal",
                "model_id": self.MODEL_ID,
                "latency_ms": latency_ms,
                "garment_category": category,
                "prompt": effective_prompt,
            }
        )

    def infer(self, person_img: Image.Image, garment_img: Image.Image, category: str, job_id: str, output_dir: str) -> TryOnResult:
        """Synchronous wrapper for infer_async."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(self.infer_async(person_img, garment_img, category, job_id, output_dir))
            else:
                return loop.run_until_complete(self.infer_async(person_img, garment_img, category, job_id, output_dir))
        except Exception:
            return asyncio.run(self.infer_async(person_img, garment_img, category, job_id, output_dir))

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "model_id": self.MODEL_ID,
            "supported_categories": self.supported_categories,
            "max_resolution": "1536x2048",
            "concurrency_limit": 10,
            "gpu_acceleration": True,
            "status": "ready" if self.is_configured() else "credentials_required",
            "provider": "fal",
            "configured": self.is_configured()
        }
