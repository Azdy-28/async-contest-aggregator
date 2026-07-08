"""
In-memory cache layer.

Design goals (mapped directly to the project requirements):

1. Decoupling: this object is the ONLY thing API handlers ever read from.
   They never call an external platform directly, so a slow/hanging
   Codeforces, LeetCode, or CodeChef request can never make a
   client-facing request slow. Only the background worker writes here.

2. "Optimized": `get_snapshot()` is O(1). The expensive work -- merging
   three platforms' contests and sorting them -- happens exactly once per
   refresh cycle inside `recompute_snapshot()`, in the background, off the
   request path. Reads never pay for that sort.

3. Resilience: a failing platform never wipes its own previously-cached
   contests. `update_platform_failure` only updates health metadata, so a
   temporarily-broken platform still serves its last known-good data
   until it recovers (better than showing nothing).
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .models import Contest, ContestsSnapshot, Platform, PlatformHealth


def _empty_health(platform: Platform) -> PlatformHealth:
    return PlatformHealth(platform=platform, healthy=False)


class InMemoryCache:
    def __init__(self, stale_after_seconds: int):
        self._lock = asyncio.Lock()
        self._raw_by_platform: Dict[Platform, List[Contest]] = {p: [] for p in Platform}
        self._health: Dict[Platform, PlatformHealth] = {p: _empty_health(p) for p in Platform}
        self._snapshot = ContestsSnapshot(
            contests=[], last_updated=None, platform_health=list(self._health.values())
        )
        self._stale_after = stale_after_seconds

    async def update_platform_success(self, platform: Platform, contests: List[Contest]) -> None:
        async with self._lock:
            self._raw_by_platform[platform] = contests
            self._health[platform] = PlatformHealth(
                platform=platform,
                healthy=True,
                last_success=datetime.now(timezone.utc),
                last_error=None,
                consecutive_failures=0,
            )

    async def update_platform_failure(self, platform: Platform, error: str) -> None:
        async with self._lock:
            prev = self._health[platform]
            self._health[platform] = PlatformHealth(
                platform=platform,
                healthy=False,
                last_success=prev.last_success,
                last_error=error,
                consecutive_failures=prev.consecutive_failures + 1,
            )

    async def recompute_snapshot(self) -> None:
        """Merge + sort all platforms' contests once, and cache the result.

        Contests that have already started (relative to now) are dropped
        here. Because this only runs once per refresh cycle, "now" is only
        ever as fresh as the last refresh -- an intentional trade-off of
        the decoupled design, documented in the README.

        Only the (expensive) contests list is cached here. Health status
        is deliberately NOT snapshotted -- see get_snapshot() below.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            merged = [
                c
                for contests in self._raw_by_platform.values()
                for c in contests
                if c.start_time > now
            ]
            merged.sort(key=lambda c: c.start_time)
            self._snapshot = ContestsSnapshot(contests=merged, last_updated=now, platform_health=[])

    async def get_snapshot(self) -> Tuple[ContestsSnapshot, bool]:
        """Return (snapshot, is_stale). O(1): no merging or sorting of contests.

        platform_health is read live from self._health rather than from the
        cached snapshot: it's cheap (three small objects) and callers of
        /health should see a platform flip unhealthy immediately, not only
        after the next full refresh cycle recomputes the contest list.
        """
        async with self._lock:
            snap = self._snapshot
            is_stale = (
                snap.last_updated is None
                or (datetime.now(timezone.utc) - snap.last_updated).total_seconds() > self._stale_after
            )
            live = ContestsSnapshot(
                contests=snap.contests,
                last_updated=snap.last_updated,
                platform_health=list(self._health.values()),
            )
            return live, is_stale
