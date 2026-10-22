from typing import Dict, Any, Optional
from .base import BaseTryOnAdapter
from .viton_hd import ProductionVitonHDAdapter
from .external_vton import ExternalVtonApiAdapter
from .fal_vton import FalFluxVtoAdapter
from .gemini_vton import GeminiVtonOrchestratorAdapter
from ..core.config import settings

class ModelRegistry:
    def __init__(self):
        self._models: Dict[str, BaseTryOnAdapter] = {}
        self._default_model_name: Optional[str] = None
        
        # 1. Register standard high-fidelity local model adapter
        viton = ProductionVitonHDAdapter()
        self.register(viton, is_default=True)

        # 2. Register Fal AI FLUX Pro VTO adapter
        fal = FalFluxVtoAdapter()
        is_fal_default = bool(settings.fal_key or settings.vton_provider.lower() in ["fal", "fal_ai", "flux"])
        self.register(fal, is_default=is_fal_default)

        # 3. Register Gemini Multimodal Vision Orchestrator adapter
        gemini = GeminiVtonOrchestratorAdapter()
        is_gemini_default = bool(settings.vton_provider.lower() in ["gemini", "gemini_vton", "gemini_vision"])
        self.register(gemini, is_default=is_gemini_default)

        # 4. Register external cloud VTON API if configured in .env
        if settings.vton_api_key or settings.vton_api_url:
            external = ExternalVtonApiAdapter()
            self.register(external, is_default=(not is_fal_default and not is_gemini_default))

    def register(self, adapter: BaseTryOnAdapter, is_default: bool = False):
        self._models[adapter.name] = adapter
        if is_default or self._default_model_name is None:
            self._default_model_name = adapter.name

    def get_model(self, name: Optional[str] = None) -> BaseTryOnAdapter:
        model_name = name or self._default_model_name
        if not model_name:
            raise ValueError("No model specified and no default model available.")
        
        # Direct lookup
        if model_name in self._models:
            return self._models[model_name]
        
        # Normalized alias lookup (e.g. 'gemini', 'gemini-vton', 'fal', 'flux-vto', 'viton')
        norm = model_name.lower().replace("_", "-")
        for key, adapter in self._models.items():
            k_norm = key.lower().replace("_", "-")
            if norm == k_norm:
                return adapter
            if "gemini" in norm and "gemini" in k_norm:
                return adapter
            if ("fal" in norm or "flux" in norm) and ("fal" in k_norm or "flux" in k_norm):
                return adapter
            if ("viton" in norm or "local" in norm) and "viton" in k_norm:
                return adapter

        raise ValueError(f"Model '{model_name}' not found in registry. Available: {list(self._models.keys())}")

    def list_models(self) -> list[Dict[str, Any]]:
        return [
            {
                **adapter.get_capabilities(),
                "is_default": (adapter.name == self._default_model_name)
            }
            for adapter in self._models.values()
        ]

    def set_default(self, name: str):
        if name not in self._models:
            raise ValueError(f"Model '{name}' not found.")
        self._default_model_name = name
