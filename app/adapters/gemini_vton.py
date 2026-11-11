"""
Gemini Multimodal Vision Virtual Try-On Orchestrator Adapter
Analyzes person posture, lighting, and garment texture using Google Gemini,
synthesizes a high-fidelity fitting prompt, and executes via Fal AI Flux VTO
or high-precision VITON-HD synthesis fallback.
"""

import os
import io
import base64
import time
import asyncio
import logging
from typing import Dict, Any, Optional, List
import httpx
from PIL import Image

from .base import BaseTryOnAdapter, TryOnResult
from .viton_hd import ProductionVitonHDAdapter
from .fal_vton import FalFluxVtoAdapter
from ..core.config import settings

logger = logging.getLogger("ai_service.adapters.gemini_vton")


class GeminiVtonOrchestratorAdapter(BaseTryOnAdapter):
    """
    Multimodal Gemini Vision + Fashion Synthesis Adapter.
    Step 1: Uses Gemini Vision to analyze (person_img, garment_img), extract drape,
            texture, collar, lighting, and generate an optimal try-on fitting prompt.
    Step 2: Dispatches to Fal AI Flux VTO (if configured) or executes high-fidelity
            VITON-HD synthesis with the synthesized prompt styling.
    """

    CANDIDATE_MODELS = [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    ]

    IMAGE_MODELS = (
        "gemini-3.1-flash-image",
        "gemini-2.5-flash-image",
        "gemini-3-pro-image",
        "gemini-3.1-flash-lite-image",
        "gemini-nano-banana-2.1",
    )

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.configured_model = model_name or settings.gemini_model or "gemini-3.6-flash"
        self._viton_fallback = ProductionVitonHDAdapter()
        self._fal_adapter = FalFluxVtoAdapter()

    @property
    def name(self) -> str:
        return "Gemini-Vision-VTO"

    @property
    def version(self) -> str:
        return "v2.5-gemini-orchestrator"

    @property
    def supported_categories(self) -> List[str]:
        return ["tops", "bottoms", "dresses", "outerwear"]

    def is_configured(self) -> bool:
        return bool(self.api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

    def validate_inputs(self, person_img: Image.Image, garment_img: Image.Image, category: str) -> tuple[bool, Optional[str]]:
        if category.lower() not in self.supported_categories:
            return False, f"Unsupported category '{category}'. Supported: {self.supported_categories}"
        if not self.is_configured():
            return False, "Gemini API key not configured. Please set GEMINI_API_KEY in ai-service/.env or via Super Admin."
        return True, None

    def preprocess(self, person_img: Image.Image, garment_img: Image.Image) -> tuple[Image.Image, Image.Image]:
        return person_img, garment_img

    async def synthesize_tryon_prompt(
        self,
        person_img: Image.Image,
        garment_img: Image.Image,
        category: str,
        user_prompt: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Multimodal analysis: inspects person and garment to craft an expert synthesis prompt.
        Returns: (synthesized_prompt, active_gemini_model_name)
        """
        if not self.is_configured():
            fallback_prompt = user_prompt or f"A natural front-facing studio shot. The {category} garment is worn naturally."
            return fallback_prompt, "local_rule_fallback"

        active_key = self.api_key or os.getenv("GEMINI_API_KEY") or settings.gemini_api_key

        orchestration_prompt = f"""
Analyze these two images. Write a highly detailed, descriptive prompt for a photorealistic fashion virtual try-on fitting:
- Image 1: The model/person image (posture, lighting, skin tone, upper/lower body proportions).
- Image 2: The garment product apparel image (fabric material, color palette, cut, collar, drape, texture, pattern, brand design).
Category: {category}.
User styling instructions: {user_prompt or 'A natural, authentic studio shot with accurate fabric drape and tailored fit.'}

Extract the artistic style, lighting, and garment drape from the second image and apply it to the person in the first image.
Output ONLY the final image generation prompt. Do not include introductory text or markdown commentary.
""".strip()

        # Try configured vision model first (skip image-only models during text prompt synthesis)
        target_model = os.getenv("GEMINI_MODEL") or self.configured_model
        is_image_only = any(tok in target_model.lower() for tok in ("image", "nano-banana"))
        models_to_try = list(self.CANDIDATE_MODELS) if is_image_only else (
            [target_model] + [m for m in self.CANDIDATE_MODELS if m != target_model]
        )

        payload = {
            "contents": [{
                "parts": [
                    {"text": orchestration_prompt},
                    {"inlineData": {"mimeType": "image/png", "data": self._pil_to_b64(person_img)}},
                    {"inlineData": {"mimeType": "image/png", "data": self._pil_to_b64(garment_img)}},
                ]
            }]
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            for m_name in models_to_try:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent"
                    resp = await client.post(
                        url,
                        headers={"x-goog-api-key": active_key, "Content-Type": "application/json"},
                        json=payload,
                    )
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

                    data = resp.json()
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    generated_text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
                    if generated_text:
                        logger.info(f"[Gemini Vision] Successfully synthesized prompt using {m_name}: '{generated_text[:120]}...'")
                        return generated_text, m_name
                except Exception as gemini_err:
                    logger.warning(f"[Gemini Vision] Model {m_name} encountered error: {gemini_err}. Trying fallback model...")

        # If all Gemini models fail or are rate-limited, return safe fallback prompt
        fallback_prompt = user_prompt or f"A natural front-facing studio shot. The {category} garment is worn naturally with realistic fabric drape."
        return fallback_prompt, "gemini_quota_fallback"

    @staticmethod
    def _pil_to_b64(img: Image.Image) -> str:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    async def _try_gemini_image_generation(
        self,
        model_id: str,
        api_key: str,
        person_img: Image.Image,
        garment_img: Image.Image,
        category: str,
        prompt: str,
        job_id: str,
        output_dir: str,
    ) -> Optional[TryOnResult]:
        """Call native Gemini image-generation REST API when an image model (e.g. gemini-3.1-flash-image) is configured."""
        t0 = time.time()
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"{job_id}.png")
        instruction = (
            f"Virtual try-on task: dress the person from the first image in the {category} garment from the second image. "
            f"Preserve the person's face, body pose, skin tone, and background naturally. {prompt}"
        ).strip()
        payload = {
            "contents": [{
                "parts": [
                    {"text": instruction},
                    {"inlineData": {"mimeType": "image/png", "data": self._pil_to_b64(person_img)}},
                    {"inlineData": {"mimeType": "image/png", "data": self._pil_to_b64(garment_img)}},
                ]
            }],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini image API HTTP {resp.status_code}: {resp.text[:240]}")

        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        for part in parts:
            inline = part.get("inlineData") or {}
            b64_data = inline.get("data")
            if b64_data:
                raw_bytes = base64.b64decode(b64_data)
                with open(out_path, "wb") as fh:
                    fh.write(raw_bytes)
                return TryOnResult(
                    job_id=job_id,
                    status="COMPLETED",
                    output_image_path=out_path,
                    output_url=f"{settings.server_url.rstrip('/')}/static/results/{os.path.basename(out_path)}",
                    model_name=self.name,
                    model_version=self.version,
                    latency_ms=(time.time() - t0) * 1000,
                    metrics={"gemini_image_model": model_id},
                )
        raise RuntimeError(f"Gemini image model '{model_id}' returned no image bytes.")

    async def infer_async(
        self,
        person_img: Image.Image,
        garment_img: Image.Image,
        category: str,
        job_id: str,
        output_dir: str,
        prompt: Optional[str] = None
    ) -> TryOnResult:
        start_time = time.time()

        # Step 1: Gemini analyzes images and crafts the enhanced prompt
        synthesized_prompt, gemini_model_used = await self.synthesize_tryon_prompt(
            person_img=person_img,
            garment_img=garment_img,
            category=category,
            user_prompt=prompt
        )

        execution_engine = "viton_hd_composite"
        result: Optional[TryOnResult] = None

        # Step 2a: Direct Gemini native image generation if an image model is selected (e.g. gemini-3.1-flash-image)
        target_model = os.getenv("GEMINI_MODEL") or self.configured_model
        active_key = self.api_key or os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
        if active_key and any(tok in target_model.lower() for tok in ("image", "nano-banana")):
            try:
                logger.info(f"[Gemini-VTO] Attempting direct Gemini image generation with '{target_model}' for job '{job_id}'...")
                result = await self._try_gemini_image_generation(
                    model_id=target_model,
                    api_key=active_key,
                    person_img=person_img,
                    garment_img=garment_img,
                    category=category,
                    prompt=synthesized_prompt,
                    job_id=job_id,
                    output_dir=output_dir,
                )
                execution_engine = f"gemini_image:{target_model}"
            except Exception as img_err:
                logger.warning(f"[Gemini-VTO] Native image model '{target_model}' failed ({img_err}). Falling back...")

        # Step 2b: Pass enhanced prompt to Fal AI FLUX Pro if configured
        if result is None and self._fal_adapter.is_configured():
            try:
                logger.info(f"[Gemini-VTO] Passing Gemini-synthesized prompt to Fal AI FLUX Pro for job '{job_id}'...")
                result = await self._fal_adapter.infer_async(
                    person_img=person_img,
                    garment_img=garment_img,
                    category=category,
                    job_id=job_id,
                    output_dir=output_dir,
                    prompt=synthesized_prompt
                )
                execution_engine = "fal_flux_vto"
            except Exception as fal_err:
                logger.warning(f"[Gemini-VTO] Fal AI invocation failed ({fal_err}). Falling back to local VITON-HD synthesis...")

        # Step 3: Resilient Fallback to VITON-HD with prompt metadata
        if result is None:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._viton_fallback.infer,
                person_img,
                garment_img,
                category,
                job_id,
                output_dir
            )
            execution_engine = "viton_hd_composite"

        total_latency = (time.time() - start_time) * 1000

        # Enhance metrics with Gemini orchestration info
        result.model_name = self.name
        result.model_version = self.version
        result.latency_ms = total_latency
        result.metrics.update({
            "orchestrator": "google_gemini_vision",
            "gemini_model": gemini_model_used,
            "gemini_prompt": synthesized_prompt[:250],
            "execution_engine": execution_engine,
            "latency_ms": round(total_latency, 2),
        })

        return result

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
            "supported_categories": self.supported_categories,
            "max_resolution": "1536x2048",
            "concurrency_limit": 12,
            "gpu_acceleration": True,
            "status": "ready" if self.is_configured() else "credentials_required",
            "provider": "gemini",
            "orchestrator": "Google Gemini Multimodal Vision",
            "fal_integration": self._fal_adapter.is_configured(),
            "viton_fallback": True,
            "active_model": self.configured_model
        }
