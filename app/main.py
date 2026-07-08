"""
FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload

This module is intentionally thin. All of the real logic (parsing, retry/
backoff, cache semantics, worker orchestration) lives in modules that have
zero third-party dependencies and are covered by tests/test_core.py. This
file's only job is to wire an aiohttp.ClientSession + the three fetchers +
the background worker + the cache together, and expose the cache over
HTTP. See tests/test_api.py for HTTP-level tests of this file.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import aiohttp
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .cache import InMemoryCache
from .config import settings
from .fetchers.codechef import CodeChefFetcher
from .fetchers.codeforces import CodeforcesFetcher
from .fetchers.leetcode import LeetCodeFetcher
from .models import Platform
from .worker import BackgroundWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("contest_pipeline")

cache = InMemoryCache(stale_after_seconds=settings.CACHE_STALE_AFTER_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    session = aiohttp.ClientSession()
    fetchers = [
        CodeforcesFetcher(session),
        LeetCodeFetcher(session),
        CodeChefFetcher(session),
    ]
    worker = BackgroundWorker(fetchers=fetchers, cache=cache, interval_seconds=settings.REFRESH_INTERVAL_SECONDS)
    task = asyncio.create_task(worker.run_forever())

    app.state.session = session
    app.state.worker = worker
    app.state.worker_task = task
    logger.info("Background worker started; refreshing every %ss", settings.REFRESH_INTERVAL_SECONDS)

    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await session.close()
        logger.info("Background worker stopped and HTTP session closed")


app = FastAPI(
    title="Contest Aggregator",
    description=(
        "Concurrent asyncio pipeline aggregating upcoming contests from "
        "Codeforces, LeetCode, and CodeChef behind an in-memory cache."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "contest-aggregator",
        "endpoints": {
            "GET /contests": "Cached upcoming contests; optional ?platform=codeforces|leetcode|codechef",
            "GET /health": "Cache freshness + per-platform fetch health",
            "POST /refresh": "Manually trigger an out-of-band refresh cycle",
            "GET /docs": "Interactive Swagger UI",
        },
    }


@app.get("/contests")
async def get_contests(
    platform: Optional[Platform] = Query(default=None, description="Filter by platform"),
):
    """
    Always served straight from the in-memory cache -- this handler never
    makes an outbound HTTP call, no matter how slow or broken an upstream
    platform currently is.
    """
    snapshot, stale = await cache.get_snapshot()
    contests = snapshot.contests
    if platform is not None:
        contests = [c for c in contests if c.platform == platform]

    body = snapshot.to_dict(stale=stale)
    body["contests"] = [c.to_dict() for c in contests]
    body["count"] = len(contests)
    return body


@app.get("/health")
async def get_health():
    snapshot, stale = await cache.get_snapshot()
    return {
        "cache_last_updated": snapshot.last_updated.isoformat() if snapshot.last_updated else None,
        "cache_stale": stale,
        "platforms": [h.to_dict() for h in snapshot.platform_health],
    }


@app.post("/refresh")
async def trigger_refresh():
    """Kick off an immediate refresh cycle without waiting for it to finish."""
    worker: BackgroundWorker = app.state.worker
    asyncio.create_task(worker.run_once())
    return {"status": "refresh triggered"}
