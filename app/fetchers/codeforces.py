"""
Codeforces fetcher.

Uses Codeforces' official, documented public API:
    GET https://codeforces.com/api/contest.list?gym=false

Verified live response shape (fields used are stable and documented):
{
  "status": "OK",
  "result": [
    {
      "id": 2232,
      "name": "Codeforces Round (Div. 2)",
      "type": "CF",
      "phase": "BEFORE",   <- "BEFORE" means the contest hasn't started yet
      "frozen": false,
      "durationSeconds": 7200,
      "startTimeSeconds": 1780151700,
      "relativeTimeSeconds": -551756
    },
    ...
  ]
}
"""

from datetime import datetime, timezone
from typing import Any, List

from ..models import Contest, Platform
from .base import BaseFetcher, PlatformParsingError

CODEFORCES_URL = "https://codeforces.com/api/contest.list?gym=false"


class CodeforcesFetcher(BaseFetcher):
    platform = Platform.CODEFORCES

    async def _fetch_raw(self) -> Any:
        async with self.session.get(CODEFORCES_URL) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _parse(self, raw: Any) -> List[Contest]:
        if not isinstance(raw, dict) or raw.get("status") != "OK":
            status = raw.get("status") if isinstance(raw, dict) else type(raw).__name__
            raise PlatformParsingError(f"unexpected top-level response (status={status!r})")

        contests: List[Contest] = []
        for item in raw["result"]:
            if item.get("phase") != "BEFORE":
                continue  
            contests.append(
                Contest(
                    platform=self.platform,
                    name=item["name"],
                    url=f"https://codeforces.com/contest/{item['id']}",
                    start_time=datetime.fromtimestamp(item["startTimeSeconds"], tz=timezone.utc),
                    duration_seconds=item["durationSeconds"],
                )
            )
        return contests
