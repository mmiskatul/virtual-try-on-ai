import json
import os
from typing import Optional
import httpx


def _sanitize_key(key: str) -> str:
    cleaned = key.replace("\\", "/").lstrip("/")
    if not cleaned or ".." in cleaned:
        raise ValueError("Invalid objectKey traversal sequence.")
    return cleaned


class PrivateStorageAdapter:
    """Private bucket object storage adapter supporting Supabase Storage REST and private local buckets."""

    def __init__(self):
        self.supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
        default_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", ".data", "private_objects")
        )
        self.local_root = os.path.abspath(os.getenv("PRIVATE_OBJECT_ROOT") or default_root)

    @property
    def driver_name(self) -> str:
        return "supabase" if (self.supabase_url and self.service_key) else "local_private"

    async def download_bytes(self, bucket: str, object_key: str) -> bytes:
        clean_key = _sanitize_key(object_key)
        if self.driver_name == "supabase":
            url = f"{self.supabase_url}/storage/v1/object/{bucket}/{clean_key}"
            headers = {"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"}
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(url, headers=headers)
                r.raise_for_status()
                return r.content

        target = os.path.abspath(os.path.join(self.local_root, bucket, clean_key))
        bucket_dir = os.path.abspath(os.path.join(self.local_root, bucket))
        if not target.startswith(bucket_dir):
            raise ValueError("Object key escapes bucket directory.")
        with open(target, "rb") as f:
            return f.read()

    async def upload_bytes(self, bucket: str, object_key: str, data: bytes, content_type: str = "image/png") -> str:
        clean_key = _sanitize_key(object_key)
        if self.driver_name == "supabase":
            url = f"{self.supabase_url}/storage/v1/object/{bucket}/{clean_key}"
            headers = {
                "apikey": self.service_key,
                "Authorization": f"Bearer {self.service_key}",
                "Content-Type": content_type,
                "x-upsert": "true",
            }
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(url, headers=headers, content=data)
                r.raise_for_status()
            return clean_key

        target = os.path.abspath(os.path.join(self.local_root, bucket, clean_key))
        bucket_dir = os.path.abspath(os.path.join(self.local_root, bucket))
        if not target.startswith(bucket_dir):
            raise ValueError("Object key escapes bucket directory.")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        with open(f"{target}.meta.json", "w", encoding="utf-8") as mf:
            json.dump({"contentType": content_type, "sizeBytes": len(data)}, mf)
        return clean_key

    async def exists(self, bucket: str, object_key: str) -> bool:
        clean_key = _sanitize_key(object_key)
        if self.driver_name == "supabase":
            url = f"{self.supabase_url}/storage/v1/object/info/{bucket}/{clean_key}"
            headers = {"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"}
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(url, headers=headers)
                return r.status_code == 200
        target = os.path.abspath(os.path.join(self.local_root, bucket, clean_key))
        return os.path.exists(target)


private_storage = PrivateStorageAdapter()

