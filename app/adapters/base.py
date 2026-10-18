from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from PIL import Image

class TryOnResult:
    def __init__(
        self,
        job_id: str,
        status: str,
        output_image_path: Optional[str] = None,
        output_url: Optional[str] = None,
        latency_ms: float = 0.0,
        model_name: str = "",
        model_version: str = "",
        metrics: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        self.job_id = job_id
        self.status = status
        self.output_image_path = output_image_path
        self.output_url = output_url
        self.latency_ms = latency_ms
        self.model_name = model_name
        self.model_version = model_version
        self.metrics = metrics or {}
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "output_url": self.output_url,
            "latency_ms": round(self.latency_ms, 2),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "metrics": self.metrics,
            "error": self.error,
        }


class BaseTryOnAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        pass

    @property
    @abstractmethod
    def supported_categories(self) -> list[str]:
        pass

    @abstractmethod
    def validate_inputs(self, person_img: Image.Image, garment_img: Image.Image, category: str) -> tuple[bool, Optional[str]]:
        pass

    @abstractmethod
    def preprocess(self, person_img: Image.Image, garment_img: Image.Image) -> tuple[Image.Image, Image.Image]:
        pass

    @abstractmethod
    def infer(self, person_img: Image.Image, garment_img: Image.Image, category: str, job_id: str, output_dir: str) -> TryOnResult:
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        pass
