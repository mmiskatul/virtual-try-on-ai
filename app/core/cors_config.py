"""
Strict Cross-Origin Resource Sharing (CORS) Configuration: AI Synthesis Engine
Restricts AI Service model inference and GPU pipelines exclusively to verified origins.
"""
import os
import re
from typing import List

# Allowed regex pattern for development ports and the official vtrystudio.com domains
CORS_ORIGIN_REGEX = r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|https://([a-zA-Z0-9-]+\.)*vtrystudio\.com)$"

# Parse explicit allowed origins from environment if provided
def get_explicit_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    # Default trusted origins
    default_origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "https://vtrystudio.com",
        "https://www.vtrystudio.com",
        "https://shop.brand.vtrystudio.com",
        "https://admin.vtrystudio.com",
        "https://api.vtrystudio.com",
    ]
    return list(set(origins + default_origins))

ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

ALLOWED_HEADERS = [
    "Content-Type",
    "Authorization",
    "x-tenant-id",
    "x-client-version",
    "x-requested-with",
    "x-nonce"
]

EXPOSED_HEADERS = [
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    "Retry-After"
]
