import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Tuple, Type

from ..config import settings
from ..models import Contest, Platform

if TYPE_CHECKING:  
    import aiohttp

try:
    import aiohttp as _aiohttp

    _NETWORK_ERRORS: Tuple[Type[BaseException], ...] = (_aiohttp.ClientError,)
except ImportError: 
    _NETWORK_ERRORS = ()

logger = logging.getLogger("contest_pipeline.fetchers")


class PlatformParsingError(Exception):
    """Raised when a platform's payload doesn't match the shape we expect.

    This is the single, well-typed exception that any DOM/schema change on
    a target platform gets converted into, so callers never have to guard
    against a long tail of raw KeyError/TypeError/IndexError variants.
    """


class PlatformFetchError(Exception):
    """Raised once all retries for a platform are exhausted in a cycle."""

    def __init__(self, platform: Platform, message: str):
        self.platform = platform
        self.message = message
        super().__init__(f"[{platform.value}] {message}")


RETRYABLE_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    asyncio.TimeoutError,
    PlatformParsingError,
) + _NETWORK_ERRORS


class BaseFetcher(ABC):
    platform: Platform

    def __init__(self, session: "aiohttp.ClientSession"):
        self.session = session

    @abstractmethod
    async def _fetch_raw(self) -> Any:
        """Perform the actual non-blocking HTTP call; return raw JSON/text."""

    @abstractmethod
    def _parse(self, raw: Any) -> List[Contest]:
        """Parse a raw payload into normalized Contest objects."""

    def _safe_parse(self, raw: Any) -> List[Contest]:
        """
        Validation boundary: converts any unexpected payload shape
        (renamed/removed field, HTML error page instead of JSON, a list
        where a dict was expected, etc.) into a single PlatformParsingError
        instead of letting a raw KeyError/TypeError/IndexError escape and
        crash the refresh cycle.
        """
        try:
            return self._parse(raw)
        except PlatformParsingError:
            raise
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            raise PlatformParsingError(f"unexpected payload shape: {exc!r}") from exc

    async def fetch_with_resilience(self) -> List[Contest]:
        """
        Fetch + parse with a timeout and exponential-backoff retries.
        Isolates this platform's failures so they can never propagate into
        the worker loop or affect any other platform's fetch.
        """
        last_exc: BaseException = RuntimeError("fetch_with_resilience: no attempts were made")
        for attempt in range(1, settings.MAX_RETRIES + 1):
            try:
                raw = await asyncio.wait_for(self._fetch_raw(), timeout=settings.HTTP_TIMEOUT_SECONDS)
                return self._safe_parse(raw)
            except RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                logger.warning(
                    "[%s] attempt %d/%d failed: %s",
                    self.platform.value,
                    attempt,
                    settings.MAX_RETRIES,
                    exc,
                )
                if attempt < settings.MAX_RETRIES:
                    await asyncio.sleep(settings.RETRY_BACKOFF_BASE ** attempt)
        raise PlatformFetchError(self.platform, str(last_exc))
