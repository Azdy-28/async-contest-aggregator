"""
CodeChef fetcher.

CodeChef has no official public API. This calls the same JSON endpoint
codechef.com/contests itself uses internally:

    GET https://www.codechef.com/api/list/contests/all
        ?sort_by=START&sorting_order=asc&offset=0&mode=all

Verified live response shape (captured directly from the endpoint):
{
  "status": "success",
  "future_contests": [
    {
      "contest_code": "START246",
      "contest_name": "Starters 246",
      "contest_start_date": "08 Jul 2026  20:00:00",
      "contest_start_date_iso": "2026-07-08T20:00:00+05:30",
      "contest_end_date_iso": "2026-07-08T22:00:00+05:30",
      "contest_duration": "120",
      ...
    },
    ...
  ],
  "present_contests": [...],
  "past_contests": [...],
  ...
}

Because this is an undocumented, internal endpoint, it is exactly the kind
of dependency that can change shape without notice -- which is precisely
what the validation layer in `base.py` exists to isolate.
"""

from datetime import datetime
from typing import Any, List

from ..models import Contest, Platform
from .base import BaseFetcher, PlatformParsingError

CODECHEF_URL = (
    "https://www.codechef.com/api/list/contests/all"
    "?sort_by=START&sorting_order=asc&offset=0&mode=all"
)


class CodeChefFetcher(BaseFetcher):
    platform = Platform.CODECHEF

    async def _fetch_raw(self) -> Any:
        headers = {"Content-Type": "application/json"}
        async with self.session.get(CODECHEF_URL, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _parse(self, raw: Any) -> List[Contest]:
        if not isinstance(raw, dict) or raw.get("status") != "success":
            raise PlatformParsingError(f"unexpected top-level response: {repr(raw)[:200]}")

        contests: List[Contest] = []
        for item in raw["future_contests"]:
            contests.append(
                Contest(
                    platform=self.platform,
                    name=item["contest_name"],
                    url=f"https://www.codechef.com/{item['contest_code']}",
                    start_time=datetime.fromisoformat(item["contest_start_date_iso"]),
                    duration_seconds=int(item["contest_duration"]) * 60,
                )
            )
        return contests
