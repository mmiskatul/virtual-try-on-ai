import hashlib
import time
from typing import Dict, Any, Optional

class IdempotencyRecord:
    def __init__(self, key: str, request_hash: str, response_payload: Dict[str, Any], status_code: int = 200):
        self.key = key
        self.request_hash = request_hash
        self.response_payload = response_payload
        self.status_code = status_code
        self.created_at = time.time()

class IdempotencyManager:
    def __init__(self, ttl_seconds: float = 86400):
        self.records: Dict[str, IdempotencyRecord] = {}
        self.ttl_seconds = ttl_seconds

    def compute_hash(self, *parts: bytes) -> str:
        h = hashlib.sha256()
        for p in parts:
            h.update(p if isinstance(p, bytes) else str(p).encode("utf-8"))
        return h.hexdigest()

    def get_record(self, key: str) -> Optional[IdempotencyRecord]:
        rec = self.records.get(key)
        if not rec:
            return None
        if time.time() - rec.created_at > self.ttl_seconds:
            del self.records[key]
            return None
        return rec

    def store_record(self, key: str, request_hash: str, response_payload: Dict[str, Any], status_code: int = 200):
        self.records[key] = IdempotencyRecord(key, request_hash, response_payload, status_code)

idempotency_manager = IdempotencyManager()
