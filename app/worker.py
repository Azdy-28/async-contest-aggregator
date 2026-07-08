"""
Background worker: the one piece of the system that ever talks to the
outside world. It fetches all platforms *concurrently* (this is the
"concurrent data pipeline ... simultaneously via non-blocking HTTP
requests" requirement), then updates the cache. Client-facing API
handlers never wait on any of this -- they only read whatever the worker
last wrote.
"""

import asyncio
import logging
from typing import List, Protocol

from .cache import InMemoryCache
from .fetchers.base import PlatformFetchError
from .models import Contest, Platform

logger = logging.getLogger("contest_pipeline.worker")


class Fetcher(Protocol):
    """Structural type so the worker can be tested with lightweight fakes
    that don't need to inherit from BaseFetcher or touch aiohttp at all."""

    platform: Platform

    async def fetch_with_resilience(self) -> List[Contest]: ...


class BackgroundWorker:
    def __init__(self, fetchers: List[Fetcher], cache: InMemoryCache, interval_seconds: int):
        self.fetchers = fetchers
        self.cache = cache
        self.interval_seconds = interval_seconds

    async def run_once(self) -> None:
        """
        Run exactly one refresh cycle: fetch every platform concurrently,
        write each result (success or failure) into the cache, then
        recompute the ready-to-serve snapshot exactly once.

        A failure from any single fetcher (already normalized to
        PlatformFetchError by fetch_with_resilience, but defensively
        handled even if something else escapes) can never prevent the
        other platforms from updating, and can never stop this method
        from returning normally -- that's the "without disrupting core
        engine uptime" requirement.
        """
        logger.info("Refresh cycle starting for %d platform(s)", len(self.fetchers))
        results = await asyncio.gather(
            *(fetcher.fetch_with_resilience() for fetcher in self.fetchers),
            return_exceptions=True,
        )

        for fetcher, result in zip(self.fetchers, results):
            if isinstance(result, PlatformFetchError):
                logger.warning("Platform fetch failed: %s", result)
                await self.cache.update_platform_failure(result.platform, result.message)
            elif isinstance(result, BaseException):
                
                logger.exception(
                    "Unexpected error in %s fetcher", fetcher.platform.value, exc_info=result
                )
                await self.cache.update_platform_failure(fetcher.platform, repr(result))
            else:
                await self.cache.update_platform_success(fetcher.platform, result)

        await self.cache.recompute_snapshot()
        logger.info("Refresh cycle complete")

    async def run_forever(self) -> None:
        """Loop `run_once` every `interval_seconds`, forever, until cancelled."""
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unhandled error in worker loop; will retry next cycle")
            await asyncio.sleep(self.interval_seconds)
