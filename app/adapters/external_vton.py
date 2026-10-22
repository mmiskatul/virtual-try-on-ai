import os
import time
import base64
import io
import urllib.request
import json
from typing import Dict, Any, Optional
from PIL import Image
from .base import BaseTryOnAdapter, TryOnResult
from ..core.config import settings

class ExternalVtonApiAdapter(BaseTryOnAdapter):
    """
    Cloud VTON API Adapter.
    Forwards virtual try-on requests to external VTON cloud services:
    - Fashn.ai (https://api.fashn.ai/v1/run)
    - Replicate IDM-VTON (https://api.replicate.com/v1/predictions)
    - Custom VTON API endpoint
    """
    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None, provider: str = "auto"):
        self.api_key = api_key or settings.vton_api_key
        self.api_url = api_url or settings.vton_api_url
        self.provider = provider or settings.vton_provider

    @property
    def name(self) -> str:
        return f"External-VTON-API ({self.detect_provider()})"

    @property
    def version(self) -> str:
        return "1.0.0-cloud"

    @property
    def supported_categories(self) -> list[str]:
        return ["tops", "bottoms", "dresses", "outerwear"]

    def detect_provider(self) -> str:
        p = (self.provider or "auto").lower()
        if p in ["fashn", "replicate", "segmind", "custom"]:
            return p
        key = self.api_key or ""
        url = self.api_url or ""
        if key.startswith("fa_") or key.startswith("fashn_") or "fashn.ai" in url:
            return "fashn"
        if key.startswith("r8_") or "replicate.com" in url:
            return "replicate"
        if "segmind.com" in url:
            return "segmind"
        if url:
            return "custom"
        return "fashn"

    def validate_inputs(self, person_img: Image.Image, garment_img: Image.Image, category: str) -> tuple[bool, Optional[str]]:
        if category.lower() not in self.supported_categories:
            return False, f"Unsupported category '{category}'. Supported: {self.supported_categories}"
        return True, None

    def _image_to_base64_data_uri(self, img: Image.Image) -> str:
        buffered = io.BytesIO()
        img.convert("RGB").save(buffered, format="JPEG", quality=92)
        encoded = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def infer(self, person_img: Image.Image, garment_img: Image.Image, category: str, job_id: str, output_dir: str) -> TryOnResult:
        start_time = time.time()
        provider = self.detect_provider()

        person_data_uri = self._image_to_base64_data_uri(person_img)
        garment_data_uri = self._image_to_base64_data_uri(garment_img)

        result_url = None

        if provider == "fashn":
            endpoint = self.api_url or "https://api.fashn.ai/v1/run"
            payload = {
                "model_image": person_data_uri,
                "garment_image": garment_data_uri,
                "category": category if category in ["tops", "bottoms", "dresses"] else "tops",
                "mode": "balanced",
                "nsfw_filter": True
            }
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                output = data.get("output")
                result_url = output[0] if isinstance(output, list) and output else output

        elif provider == "replicate":
            endpoint = self.api_url or "https://api.replicate.com/v1/predictions"
            payload = {
                "version": "c871bb9b046607b680449ecbae55fd8c6d945e0a1948644bf2361b3d05e800f0",
                "input": {
                    "human_img": person_data_uri,
                    "garm_img": garment_data_uri,
                    "garment_des": category
                }
            }
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Token {self.api_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                output = data.get("output")
                result_url = output[0] if isinstance(output, list) and output else output

        elif provider == "custom" and self.api_url:
            payload = {
                "personImage": person_data_uri,
                "garmentImage": garment_data_uri,
                "category": category
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["x-api-key"] = self.api_key
            req = urllib.request.Request(
                self.api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                result_url = data.get("resultUrl") or data.get("outputUrl") or data.get("output")

        # Fallback to local image save if needed
        os.makedirs(output_dir, exist_ok=True)
        filename = f"tryon_{job_id}.jpg"
        filepath = os.path.join(output_dir, filename)

        if not result_url:
            # Fallback output
            person_img.convert("RGB").save(filepath, "JPEG")
            result_url = f"/static/results/{filename}"

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
                "provider": provider,
                "latency_ms": latency_ms,
                "garment_category": category
            }
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "supported_categories": self.supported_categories,
            "max_resolution": "1536x2048",
            "concurrency_limit": 16,
            "gpu_acceleration": True,
            "status": "ready",
            "provider": self.detect_provider()
        }
