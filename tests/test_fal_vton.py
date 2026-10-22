"""
Unit test for FalFluxVtoAdapter (Fal AI flux-pro/v1/vto)
"""
import sys
import os
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.adapters.fal_vton import FalFluxVtoAdapter
from app.adapters.registry import ModelRegistry

def test_fal_adapter_metadata():
    adapter = FalFluxVtoAdapter()
    assert adapter.name == "Fal-AI-Flux-VTO"
    assert adapter.version == "v1.0-flux-pro"
    assert "tops" in adapter.supported_categories
    assert "dresses" in adapter.supported_categories

def test_fal_adapter_validation_without_key():
    adapter = FalFluxVtoAdapter()
    adapter.api_key = None
    if "FAL_KEY" in os.environ:
        del os.environ["FAL_KEY"]
    if "FAL_API_KEY" in os.environ:
        del os.environ["FAL_API_KEY"]
    
    img = Image.new("RGB", (100, 100))
    valid, err = adapter.validate_inputs(img, img, "tops")
    assert not valid
    assert "Fal AI credentials not configured" in err

def test_fal_adapter_validation_with_key():
    adapter = FalFluxVtoAdapter(api_key="fal_test_key_1234567890abcdef")
    img = Image.new("RGB", (100, 100))
    valid, err = adapter.validate_inputs(img, img, "tops")
    assert valid
    assert err is None

def test_fal_adapter_prompt_generation():
    adapter = FalFluxVtoAdapter()
    assert "dress" in adapter.default_prompt_for_category("dresses")
    assert "garment" in adapter.default_prompt_for_category("tops")

def test_fal_model_registry_lookup():
    reg = ModelRegistry()
    fal = reg.get_model("fal")
    assert fal.name == "Fal-AI-Flux-VTO"
    
    fal_by_id = reg.get_model("fal-ai/flux-pro/v1/vto")
    assert fal_by_id.name == "Fal-AI-Flux-VTO"
    
    fal_by_alias = reg.get_model("fal-flux-vto")
    assert fal_by_alias.name == "Fal-AI-Flux-VTO"

if __name__ == "__main__":
    test_fal_adapter_metadata()
    test_fal_adapter_validation_without_key()
    test_fal_adapter_validation_with_key()
    test_fal_adapter_prompt_generation()
    test_fal_model_registry_lookup()
    print("[PASS] All FalFluxVtoAdapter unit tests passed!")
