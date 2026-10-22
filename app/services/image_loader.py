"""
Image Loader Service
Safely loads image bytes from multipart UploadFile, base64 data URIs, HTTP(S) remote URLs,
local filesystem paths, or preset references, with resilient fallback synthesis.
"""
import io
import os
import base64
from typing import Tuple, Union, Optional
from PIL import Image, ImageDraw
import httpx
from fastapi import UploadFile

def generate_preset_person() -> bytes:
    """Generates a high-quality model portrait canvas (300x400) for testing/fallback."""
    img = Image.new("RGB", (300, 400), color=(235, 215, 200))
    draw = ImageDraw.Draw(img)
    # Head & torso representation
    draw.ellipse((120, 20, 180, 80), fill=(210, 180, 160))
    draw.rectangle((100, 85, 200, 260), fill=(220, 195, 175))
    draw.rectangle((110, 260, 145, 390), fill=(80, 80, 90))
    draw.rectangle((155, 260, 190, 390), fill=(80, 80, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()

def generate_preset_garment(category: str = "tops") -> bytes:
    """Generates a high-contrast garment image (200x200) for testing/fallback."""
    img = Image.new("RGBA", (200, 200), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if category.lower() in ("bottoms", "pants"):
        draw.polygon([(60, 20), (140, 20), (150, 180), (110, 180), (100, 80), (90, 180), (50, 180)], fill=(30, 64, 175, 255))
    elif category.lower() in ("dresses", "dress"):
        draw.polygon([(70, 20), (130, 20), (160, 180), (40, 180)], fill=(192, 38, 211, 255))
    else:
        # Standard top / shirt
        draw.polygon([(40, 20), (160, 20), (190, 70), (160, 90), (150, 60), (150, 180), (50, 180), (50, 60), (40, 90), (10, 70)], fill=(16, 185, 129, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

async def resolve_image_payload(
    source: Union[UploadFile, bytes, str, None],
    fallback_type: str = "person",
    category: str = "tops",
) -> Tuple[bytes, str]:
    """
    Extracts binary image data and an identifier filename from any accepted representation.
    Returns (image_bytes, filename).
    """
    if source is None:
        if fallback_type == "person":
            return generate_preset_person(), "preset_person.jpg"
        return generate_preset_garment(category), "preset_garment.png"

    # 1. FastAPI UploadFile
    if isinstance(source, UploadFile):
        data = await source.read()
        fname = source.filename or f"{fallback_type}.jpg"
        return data, fname

    # 2. Raw bytes
    if isinstance(source, bytes):
        return source, f"{fallback_type}.jpg"

    # 3. String representations
    if isinstance(source, str):
        source = source.strip()

        # 3a. Base64 Data URI
        if source.startswith("data:image/"):
            try:
                header, encoded = source.split(",", 1)
                data = base64.b64decode(encoded)
                ext = "png" if "png" in header else "jpg"
                return data, f"{fallback_type}_b64.{ext}"
            except Exception:
                pass

        # 3b. Remote HTTP(S) URL
        if source.startswith("http://") or source.startswith("https://"):
            try:
                async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                    resp = await client.get(source)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        fname = os.path.basename(source.split("?")[0]) or f"{fallback_type}_remote.jpg"
                        return resp.content, fname
            except Exception:
                # If network is unreachable or blocked, fall back safely
                pass

        # 3c. Local file path
        if os.path.isfile(source):
            try:
                with open(source, "rb") as f:
                    return f.read(), os.path.basename(source)
            except Exception:
                pass

        # 3d. Pure Base64 string without data: prefix
        if len(source) > 200 and not source.startswith(("/", "\\", ".")):
            try:
                decoded = base64.b64decode(source)
                if len(decoded) > 50:
                    return decoded, f"{fallback_type}_raw_b64.jpg"
            except Exception:
                pass

    # Safe fallback if input was invalid or empty
    if fallback_type == "person":
        return generate_preset_person(), "fallback_person.jpg"
    return generate_preset_garment(category), "fallback_garment.png"
