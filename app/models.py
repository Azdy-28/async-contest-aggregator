"""
Domain models for the contest aggregation pipeline.

These are plain stdlib `dataclasses`, not pydantic models. FastAPI only
needs pydantic for its own request/response machinery internally -- our
own domain logic (fetchers, cache, worker) has zero third-party
dependencies, which is what lets the whole core pipeline be unit tested
with nothing but the standard library.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class Platform(str, Enum):
    CODEFORCES = "codeforces"
    LEETCODE = "leetcode"
    CODECHEF = "codechef"


@dataclass
class Contest:
    platform: Platform
    name: str
    url: str
    start_time: datetime  
    duration_seconds: int

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "name": self.name,
            "url": self.url,
            "start_time": self.start_time.isoformat(),
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class PlatformHealth:
    platform: Platform
    healthy: bool
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "healthy": self.healthy,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class ContestsSnapshot:
    """A fully-computed, ready-to-serve view of the cache at a point in time."""

    contests: List[Contest] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    platform_health: List[PlatformHealth] = field(default_factory=list)

    def to_dict(self, stale: bool) -> dict:
        return {
            "contests": [c.to_dict() for c in self.contests],
            "count": len(self.contests),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "stale": stale,
            "platform_health": [h.to_dict() for h in self.platform_health],
        }
