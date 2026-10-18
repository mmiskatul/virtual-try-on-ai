from typing import Dict, Any, Optional
from .base import BaseTryOnAdapter
from .viton_hd import ProductionVitonHDAdapter

class ModelRegistry:
    def __init__(self):
        self._models: Dict[str, BaseTryOnAdapter] = {}
        self._default_model_name: Optional[str] = None
        
        # Register standard high-fidelity model adapter
        viton = ProductionVitonHDAdapter()
        self.register(viton, is_default=True)

    def register(self, adapter: BaseTryOnAdapter, is_default: bool = False):
        self._models[adapter.name] = adapter
        if is_default or self._default_model_name is None:
            self._default_model_name = adapter.name

    def get_model(self, name: Optional[str] = None) -> BaseTryOnAdapter:
        model_name = name or self._default_model_name
        if model_name not in self._models:
            raise ValueError(f"Model '{model_name}' not found in registry.")
        return self._models[model_name]

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
