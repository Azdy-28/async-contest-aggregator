# Contest Aggregator

A concurrent, `asyncio`-based data pipeline that aggregates upcoming contest
schedules from **Codeforces**, **LeetCode**, and **CodeChef** in parallel via
non-blocking HTTP, keeps them in an optimized in-memory cache refreshed by a
background worker, and serves them over a small HTTP API that never talks to
the network itself.

```
                     ┌─────────────────────────────────────────────┐
                     │              BackgroundWorker                │
                     │   (asyncio.gather -- runs every N seconds)   │
                     │                                               │
     ┌───────────┐   │   ┌──────────────┐  ┌──────────┐  ┌────────┐ │
     │ Codeforces│◄──┼───┤ Codeforces   │  │ LeetCode │  │CodeChef│ │
     │  (real API)│  │   │ Fetcher      │  │ Fetcher  │  │Fetcher │ │
     └───────────┘   │   └──────┬───────┘  └────┬─────┘  └───┬────┘ │
     ┌───────────┐   │          │  each wrapped in            │      │
     │  LeetCode │◄──┼──────────┤  fetch_with_resilience()    │      │
     │ (GraphQL) │   │          │  (timeout + retry + backoff  │      │
     └───────────┘   │          │   + payload validation)      │      │
     ┌───────────┐   │          └──────────────┬───────────────┘      │
     │  CodeChef │◄──┼─────────────────────────┘                      │
     │(JSON API) │   └──────────────────────┬────────────────────────┘
     └───────────┘                          │ writes only
                                             ▼
                                   ┌───────────────────┐
                                   │   InMemoryCache     │
                                   │  (asyncio.Lock,      │
                                   │   O(1) reads)        │
                                   └──────────┬───────────┘
                                              │ reads only, never awaits network
                                              ▼
                                   ┌───────────────────┐
                                   │   FastAPI (main.py) │
                                   │  GET /contests       │
                                   │  GET /health         │
                                   │  POST /refresh       │
                                   └───────────────────┘
```

## How the three requirements map to code

| Requirement | Where |
|---|---|
| Concurrent pipeline aggregating 3 platforms simultaneously via non-blocking HTTP | `app/worker.py` (`asyncio.gather` over all fetchers) + `app/fetchers/*.py` (each uses `aiohttp`, never `requests`) |
| Background worker periodically updating an optimized in-memory cache, decoupled from client-facing requests | `app/worker.py` (`run_forever`) + `app/cache.py` (`InMemoryCache`) + `app/main.py` (API handlers only ever call `cache.get_snapshot()`) |
| Fault-tolerant parsing validation isolating DOM/API payload changes without disrupting uptime | `app/fetchers/base.py` (`_safe_parse`, `fetch_with_resilience`) + `app/worker.py` (`run_once` never lets one platform's exception affect another, or escape) |

## Tech stack

- **Python 3.10+**
- **asyncio** -- everything runs on one event loop: the HTTP server, the background worker, and all three platform fetches
- **aiohttp** -- non-blocking HTTP client for the platform fetches (and, on the server side, what `uvicorn`/`FastAPI` run on)
- **FastAPI** -- the client-facing API layer (see "Role of FastAPI" below)
- **In-memory cache** -- a hand-rolled `asyncio.Lock`-protected store (`app/cache.py`), not Redis/Memcached -- deliberately, per the spec

Domain models (`app/models.py`) use plain stdlib `dataclasses` rather than
Pydantic, so the entire pipeline core (parsing, cache, worker) has **zero
third-party dependencies** and can be unit tested with nothing but
`unittest`. FastAPI still uses Pydantic internally for its own request
validation -- that's unavoidable and unrelated to our domain models.

## Project structure

```
contest-aggregator/
├── app/
│   ├── config.py              # env-var driven settings
│   ├── models.py               # Contest, PlatformHealth, ContestsSnapshot (dataclasses)
│   ├── cache.py                 # InMemoryCache -- the decoupling layer
│   ├── worker.py                 # BackgroundWorker -- concurrent fetch + refresh loop
│   ├── main.py                    # FastAPI app, routes, lifespan wiring
│   └── fetchers/
│       ├── base.py                 # retry/timeout/validation boilerplate, shared by all 3
│       ├── codeforces.py            # real Codeforces public API
│       ├── leetcode.py               # real LeetCode GraphQL endpoint
│       └── codechef.py                # real CodeChef internal JSON endpoint
├── tests/
│   ├── test_core.py            # stdlib-only: parsing, cache, retries, worker
│   └── test_api.py              # needs the real stack: HTTP layer end-to-end
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

## Setup & how to run it

**Where:** on any machine with internet access and Python 3.10+ -- your
laptop, a VM, a container, etc. It needs to reach `codeforces.com`,
`leetcode.com`, and `codechef.com` directly, so it won't work somewhere
with restricted/no outbound network access.

```bash
# 1. open the root folder
cd contest-aggregator

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the API server
uvicorn app.main:app --reload
```

Then open:
- **http://127.0.0.1:8000/docs** -- interactive Swagger UI (auto-generated by FastAPI)
- **http://127.0.0.1:8000/contests** -- the live cached contest list
- **http://127.0.0.1:8000/health** -- per-platform fetch health + cache freshness

The cache is empty for a brief moment on first startup until the worker's
first refresh cycle completes (typically a couple of seconds) -- watch the
terminal logs, you'll see `Refresh cycle starting...` / `Refresh cycle
complete`.

## API reference

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Lists available endpoints |
| `/contests` | GET | All cached upcoming contests, merged and sorted by start time. Optional `?platform=codeforces\|leetcode\|codechef` |
| `/health` | GET | Cache staleness + per-platform health (last success, last error, consecutive failures) |
| `/refresh` | POST | Manually triggers an out-of-band refresh cycle without waiting for the next scheduled one |
| `/docs` | GET | Swagger UI |
