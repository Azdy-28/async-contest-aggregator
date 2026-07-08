"""
LeetCode fetcher.

LeetCode has no documented public REST API for contests. This calls the
same unauthenticated GraphQL endpoint leetcode.com's own contest page uses:

    POST https://leetcode.com/graphql/
    {"query": "query topTwoContests { topTwoContests { title titleSlug startTime duration } }",
     "operationName": "topTwoContests"}

Verified response shape:
{"data": {"topTwoContests": [
    {"title": "Weekly Contest 512", "titleSlug": "weekly-contest-512",
     "startTime": 1783500600, "duration": 5400},
    {"title": "Biweekly Contest 163", "titleSlug": "biweekly-contest-163",
     "startTime": 1784105400, "duration": 5400}
]}}

Known, real limitation (not a bug in this pipeline): unauthenticated,
undocumented access only exposes the *next two* contests (one Weekly, one
Biweekly) -- there is no public "list all upcoming LeetCode contests"
endpoint. This is called out explicitly rather than papered over.

LeetCode also fronts this endpoint with bot-detection, so requests without
a browser-like User-Agent/Referer are frequently rejected outright. If that
happens here, `fetch_with_resilience` isolates it as a normal per-platform
failure -- Codeforces and CodeChef are entirely unaffected.
"""

from datetime import datetime, timezone
from typing import Any, List

from ..models import Contest, Platform
from .base import BaseFetcher, PlatformParsingError

LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql/"
LEETCODE_QUERY = "query topTwoContests { topTwoContests { title titleSlug startTime duration } }"
LEETCODE_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://leetcode.com/contest/",
}


class LeetCodeFetcher(BaseFetcher):
    platform = Platform.LEETCODE

    async def _fetch_raw(self) -> Any:
        payload = {"query": LEETCODE_QUERY, "operationName": "topTwoContests"}
        async with self.session.post(
            LEETCODE_GRAPHQL_URL, json=payload, headers=LEETCODE_HEADERS
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _parse(self, raw: Any) -> List[Contest]:
        if not isinstance(raw, dict) or "data" not in raw or raw["data"] is None:
            raise PlatformParsingError(f"missing 'data' key in GraphQL response: {repr(raw)[:200]}")

        top_two = raw["data"]["topTwoContests"]
        contests: List[Contest] = []
        for item in top_two:
            contests.append(
                Contest(
                    platform=self.platform,
                    name=item["title"],
                    url=f"https://leetcode.com/contest/{item['titleSlug']}",
                    start_time=datetime.fromtimestamp(item["startTime"], tz=timezone.utc),
                    duration_seconds=item["duration"],
                )
            )
        return contests
