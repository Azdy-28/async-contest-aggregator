"""
Central configuration for the contest aggregation pipeline.

Everything here is overridable via environment variables so the refresh
cadence, timeouts, and retry behaviour can be tuned per-deployment without
touching code. Values are read once at import time.

NOTE: this is intentionally a plain (non-frozen) class rather than an
immutable dataclass so that tests can monkeypatch individual fields (e.g.
temporarily shortening HTTP_TIMEOUT_SECONDS for a fast resilience test).
"""

import os

try:  
    from dotenv import load_dotenv

    load_dotenv()  
except ImportError:
    pass  


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    REFRESH_INTERVAL_SECONDS: int = _int_env("REFRESH_INTERVAL_SECONDS", 300)

    HTTP_TIMEOUT_SECONDS: float = _float_env("HTTP_TIMEOUT_SECONDS", 10.0)

    MAX_RETRIES: int = _int_env("MAX_RETRIES", 3)

    RETRY_BACKOFF_BASE: float = _float_env("RETRY_BACKOFF_BASE", 1.5)

    CACHE_STALE_AFTER_SECONDS: int = _int_env("CACHE_STALE_AFTER_SECONDS", 900)


settings = Settings()
