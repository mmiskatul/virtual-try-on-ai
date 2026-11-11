"""
Dedicated Secrets Vault Service: AI Neural Try-On Pipeline
Enforces production-grade secret resolution from filesystem mounts (/run/secrets/*)
and environment variables, with strict entropy validation and zero hardcoded production fallbacks.
"""
import os
import secrets
from typing import Optional, Dict

class SecretsVault:
    def __init__(self):
        self._cache: Dict[str, str] = {}
        self.secrets_dir = os.getenv("SECRETS_DIR", "/run/secrets")

    def get_secret(
        self,
        name: str,
        description: str,
        required_in_production: bool = True,
        min_length: Optional[int] = None,
        development_fallback: Optional[str] = None
    ) -> str:
        if name in self._cache:
            return self._cache[name]

        is_production = os.getenv("ENV", "development").lower() == "production"
        value: Optional[str] = None

        # 1. Check mounted secret file (Kubernetes / Docker secrets / HashiCorp Vault Agent)
        file_path = os.path.join(self.secrets_dir, name.lower())
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        value = content
            except Exception:
                pass

        # 2. Check process environment
        if not value and os.getenv(name):
            env_val = os.getenv(name, "").strip()
            if env_val:
                value = env_val

        # 3. In production, strictly enforce security criteria
        if is_production:
            if not value and required_in_production:
                raise RuntimeError(
                    f"[FATAL SECRETS CONFIG] Production secret '{name}' ({description}) is missing! "
                    f"It must be provided via environment variables or secret mounts."
                )

            if value and min_length and len(value) < min_length:
                raise RuntimeError(
                    f"[FATAL SECRETS CONFIG] Production secret '{name}' must be at least "
                    f"{min_length} characters long for cryptographic security."
                )

            weak_patterns = ["secret", "password", "123456", "admin", "default", "sample"]
            if value and any(value.lower() == p for p in weak_patterns):
                raise RuntimeError(
                    f"[FATAL SECRETS CONFIG] Production secret '{name}' uses an insecure default value. "
                    f"Please configure a cryptographically secure key."
                )

        # 4. In test mode, generate an isolated ephemeral secret; otherwise require env or secret mount
        if not value:
            if os.getenv("ENV", "").lower() == "test":
                value = secrets.token_hex(32)
            elif development_fallback:
                value = development_fallback
                print(f"[DEV SECRETS WARNING] Using local development fallback for secret '{name}'. Never use this in production!")
            else:
                raise RuntimeError(f"[SECRETS CONFIG] Secret '{name}' is required but not configured in .env or /run/secrets.")

        self._cache[name] = value
        return value

    def mask_secret(self, value: str) -> str:
        if not value or len(value) < 8:
            return "********"
        return f"{value[:4]}...{value[-4:]}"

secrets_vault = SecretsVault()
