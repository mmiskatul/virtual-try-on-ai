from abc import ABC, abstractmethod
import asyncio
from typing import Dict, Any, Optional
from PIL import Image
from .base import BaseTryOnAdapter, TryOnResult


class TryOnModel(ABC):
    """Formal async model lifecycle contract (Prompt Section 7.3) supporting lazy loading/unloading."""

    @abstractmethod
    async def load(self) -> None:
        pass

    @abstractmethod
    async def generate(self, person_image: Image.Image, garment_image: Image.Image, options: Dict[str, Any]) -> TryOnResult:
        pass

    @abstractmethod
    async def unload(self) -> None:
        pass

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        pass


class AdapterTryOnModelBridge(TryOnModel):
    """Bridges synchronous/async BaseTryOnAdapter implementations cleanly into lazy-loaded TryOnModel lifecycle."""

    def __init__(self, adapter: BaseTryOnAdapter, output_dir: str):
        self._adapter = adapter
        self._output_dir = output_dir
        self._loaded = False

    async def load(self) -> None:
        if not self._loaded:
            self._loaded = True

    async def generate(self, person_image: Image.Image, garment_image: Image.Image, options: Dict[str, Any]) -> TryOnResult:
        await self.load()
        category = str(options.get("category", "tops"))
        job_id = str(options.get("job_id", "job_unknown"))
        ok, err_msg = self._adapter.validate_inputs(person_image, garment_image, category)
        if not ok:
            return TryOnResult(
                job_id=job_id,
                status="failed",
                model_name=self._adapter.name,
                model_version=self._adapter.version,
                error=err_msg or "Input validation failed",
            )
        p_proc, g_proc = self._adapter.preprocess(person_image, garment_image)
        return await asyncio.to_thread(
            self._adapter.infer,
            p_proc,
            g_proc,
            category,
            job_id,
            self._output_dir,
        )

    async def unload(self) -> None:
        self._loaded = False

    def health(self) -> Dict[str, Any]:
        return {
            "name": self._adapter.name,
            "version": self._adapter.version,
            "loaded": self._loaded,
            "supported_categories": self._adapter.supported_categories,
        }

