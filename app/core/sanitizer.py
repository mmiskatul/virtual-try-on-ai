"""
Boundary Input Validation and Sanitization Service
Protects AI Virtual Try-On API boundary against injection exploits (SQLi, XSS, Path Traversal, Null Bytes).
"""
import re
import json
import urllib.parse
from typing import Any, Dict, Optional, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Known SQL Injection signatures: Tautology, UNION, subqueries, destructive queries
SQL_INJECTION_REGEX = re.compile(
    r"(\b(UNION\s+(ALL\s+)?SELECT|DROP\s+TABLE|ALTER\s+TABLE|DELETE\s+FROM|INSERT\s+INTO|TRUNCATE\s+TABLE|EXEC(\s|\()+|BENCHMARK\(|WAITFOR\s+DELAY)\b|('|\b)\s*OR\s+('?\d+'?='?\d+'?|true\b)|--\s*$|/\*.*?\*/)",
    re.IGNORECASE
)

# Known XSS script injection signatures: script tags, inline event handlers, javascript/vbscript/data pseudo-protocols
XSS_INJECTION_REGEX = re.compile(
    r"(<script\b|<[^>]+(onload|onerror|onclick|onmouseover|onfocus|onblur|onchange|onsubmit)\s*=|javascript:|vbscript:|data:[^\s\"'>]+)",
    re.IGNORECASE
)

# Null byte and path traversal injection signatures
NULL_BYTE_REGEX = re.compile(r"(\0|%00)")
PATH_TRAVERSAL_REGEX = re.compile(r"(\.\.[/\\])")


def inspect_string(value: str, field_name: str = "") -> Optional[Dict[str, str]]:
    """
    Validate string input against SQLi, XSS, Path Traversal, and Null Byte exploits.
    Returns None if valid, or a dict with threat_type and field if an attack pattern is matched.
    """
    if not isinstance(value, str):
        return None

    if NULL_BYTE_REGEX.search(value):
        return {"threat_type": "NULL_BYTE", "field": field_name}

    if PATH_TRAVERSAL_REGEX.search(value):
        return {"threat_type": "PATH_TRAVERSAL", "field": field_name}

    if SQL_INJECTION_REGEX.search(value):
        return {"threat_type": "SQLI", "field": field_name}

    if XSS_INJECTION_REGEX.search(value):
        return {"threat_type": "XSS", "field": field_name}

    return None


def sanitize_html(str_val: str, field_name: str = "") -> str:
    """
    Cleans residual HTML markup, stripping angle brackets from general inputs.
    Passwords, API keys, tokens, and hashes are preserved intact.
    """
    lower = field_name.lower()
    if any(k in lower for k in ("key", "token", "secret", "password", "hash")):
        return str_val

    # Strip HTML tags
    cleaned = re.sub(r"<[^>]*>?", "", str_val)
    cleaned = re.sub(r"javascript:", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def sanitize_data(data: Any, path_prefix: str = "") -> Tuple[Any, Optional[Dict[str, str]]]:
    """
    Recursively inspect and sanitize payloads, queries, and dictionary/list structures.
    """
    if data is None or isinstance(data, (int, float, bool, bytes)):
        return data, None

    if isinstance(data, str):
        threat = inspect_string(data, path_prefix)
        if threat:
            return data, threat
        return sanitize_html(data, path_prefix), None

    if isinstance(data, list):
        clean_list = []
        for i, item in enumerate(data):
            clean_item, threat = sanitize_data(item, f"{path_prefix}[{i}]")
            if threat:
                return data, threat
            clean_list.append(clean_item)
        return clean_list, None

    if isinstance(data, dict):
        clean_dict = {}
        for key, val in data.items():
            # Defense against prototype/dunder pollution
            if key in ("__proto__", "constructor", "prototype", "__class__", "__globals__"):
                continue

            k_threat = inspect_string(str(key), f"{path_prefix}.{key}")
            if k_threat:
                return data, k_threat

            clean_val, threat = sanitize_data(val, f"{path_prefix}.{key}")
            if threat:
                return data, threat
            clean_dict[key] = clean_val
        return clean_dict, None

    return data, None


class InputSanitizerMiddleware(BaseHTTPMiddleware):
    """
    Starlette ASGI Middleware intercepting all incoming HTTP requests at the API boundary.
    Inspects URL path, query parameters, HTTP headers, and JSON request bodies.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. URL Path Inspection
        raw_path = urllib.parse.unquote(request.url.path)
        path_threat = inspect_string(raw_path, "path")
        if path_threat:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "SecurityViolation",
                    "code": f"INJECTION_ATTACK_DETECTED_{path_threat['threat_type']}",
                    "message": f"Malicious {path_threat['threat_type']} payload blocked at API boundary in path parameter.",
                },
            )

        # 2. Query Parameters Inspection
        for key, val in request.query_params.items():
            k_threat = inspect_string(key, f"query.{key}")
            if k_threat:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "SecurityViolation",
                        "code": f"INJECTION_ATTACK_DETECTED_{k_threat['threat_type']}",
                        "message": f"Malicious {k_threat['threat_type']} payload blocked at API boundary in query key '{key}'.",
                    },
                )
            v_threat = inspect_string(val, f"query.{key}")
            if v_threat:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "SecurityViolation",
                        "code": f"INJECTION_ATTACK_DETECTED_{v_threat['threat_type']}",
                        "message": f"Malicious {v_threat['threat_type']} payload blocked at API boundary in query parameter '{key}'.",
                    },
                )

        # 3. HTTP Headers Inspection
        for h_key, h_val in request.headers.items():
            # Check for null bytes, SQLi, and XSS in header values
            if NULL_BYTE_REGEX.search(h_val):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "SecurityViolation",
                        "code": "INJECTION_ATTACK_DETECTED_NULL_BYTE",
                        "message": f"Null byte detected in HTTP header '{h_key}'.",
                    },
                )
            if SQL_INJECTION_REGEX.search(h_val):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "SecurityViolation",
                        "code": "INJECTION_ATTACK_DETECTED_SQLI",
                        "message": f"Malicious SQLI payload blocked at API boundary in HTTP header '{h_key}'.",
                    },
                )
            if XSS_INJECTION_REGEX.search(h_val):
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "SecurityViolation",
                        "code": "INJECTION_ATTACK_DETECTED_XSS",
                        "message": f"Malicious XSS payload blocked at API boundary in HTTP header '{h_key}'.",
                    },
                )

        # 4. JSON Payload Inspection
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            body_bytes = await request.body()
            if body_bytes:
                try:
                    payload = json.loads(body_bytes.decode("utf-8"))
                    clean_data, threat = sanitize_data(payload, "body")
                    if threat:
                        return JSONResponse(
                            status_code=400,
                            content={
                                "error": "SecurityViolation",
                                "code": f"INJECTION_ATTACK_DETECTED_{threat['threat_type']}",
                                "message": f"Malicious {threat['threat_type']} payload blocked at API boundary in body field '{threat['field']}'.",
                            },
                        )
                except json.JSONDecodeError:
                    pass

        return await call_next(request)
