"""Local configuration; credentials are excluded from experiment metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def load_env(path: Path) -> None:
    """Read simple KEY=VALUE lines without executing or expanding values."""
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid configuration line {number}; use KEY=VALUE")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed quote at configuration line {number}")
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    provider: str = "mock"
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = 60.0
    max_completion_tokens: int = 1024
    temperature: float | None = None

    @classmethod
    def from_env(cls, provider: str | None = None) -> Settings:
        try:
            temperature = os.getenv("PROMPTSHIELD_TEMPERATURE", "").strip()
            return cls(
                provider=provider or os.getenv("PROMPTSHIELD_PROVIDER", "mock"),
                model=os.getenv("PROMPTSHIELD_MODEL", "").strip(),
                base_url=os.getenv("PROMPTSHIELD_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
                api_key=os.getenv("PROMPTSHIELD_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
                timeout_seconds=float(os.getenv("PROMPTSHIELD_TIMEOUT_SECONDS", "60")),
                max_completion_tokens=int(os.getenv("PROMPTSHIELD_MAX_COMPLETION_TOKENS", "1024")),
                temperature=float(temperature) if temperature else None,
            )
        except ValueError:
            raise ValueError("Timeout, token limit and temperature must be valid numbers") from None

    def validate(self) -> None:
        if self.provider not in {"mock", "api"}:
            raise ValueError("provider must be mock or api")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout must be finite and positive")
        if self.max_completion_tokens <= 0:
            raise ValueError("max_completion_tokens must be positive")
        if self.temperature is not None and (
            not math.isfinite(self.temperature) or not 0 <= self.temperature <= 2
        ):
            raise ValueError("temperature must be between 0 and 2")
        if self.provider == "api":
            if not self.model or not self.api_key.strip():
                raise ValueError("API mode requires PROMPTSHIELD_MODEL and PROMPTSHIELD_API_KEY (or OPENAI_API_KEY)")
            if any(character in self.api_key for character in "\r\n"):
                raise ValueError("API key must be on a single line")
            url = urlsplit(self.base_url)
            try:
                url.port
            except ValueError:
                raise ValueError("Invalid API base URL port") from None
            if not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("base URL must not contain credentials, query parameters or a fragment")
            if url.scheme != "https" and not (
                url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("API base URL requires HTTPS (HTTP is allowed only for local tests)")

    def public_metadata(self) -> dict:
        return {
            "provider": self.provider,
            "requested_model": self.model if self.provider == "api" else "mock-smoke-v1",
            "base_url": self.base_url if self.provider == "api" else None,
            "timeout_seconds": self.timeout_seconds,
            "max_completion_tokens": self.max_completion_tokens,
            "temperature": self.temperature,
        }
