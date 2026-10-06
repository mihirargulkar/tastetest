# TasteTest (LTO Rollout Planner) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a public web app where a coffee-chain manager describes a limited-time offer (LTO) and an agent ranks the chain's stores by local taste fit (from Qloo), with a per-store brief.

**Architecture:** A single FastAPI service. It runs a Claude tool-use loop that turns the LTO into a Qloo "taste signature", scores stores deterministically from Qloo heatmaps (z-score against the chain average), and streams a tool trace to the browser over SSE. The same service serves a React + MapLibre frontend built as static files. All Qloo response shapes are isolated in one module (`qloo.py`) so a mismatch with the live API is a one-file fix.

**Tech Stack:** Python 3.12, FastAPI, httpx, `anthropic` SDK (async), pytest + pytest-asyncio; React 18 + Vite + maplibre-gl; Docker on Render.

**Spec:** `docs/superpowers/specs/2026-10-02-lto-rollout-planner-design.md`

## Global Constraints

- Qloo base URL: `https://hackathon.api.qloo.com`. Auth header: `X-Api-Key`. All Insights calls are `GET /v2/insights` with query params. Never use `/recommendations` or `/recs`.
- Supported Qloo `filter.type` values only: `urn:entity:artist|book|brand|destination|movie|person|place|podcast|tv_show|video_game`, plus `urn:heatmap` and `urn:tag` for heatmap/taste analysis.
- Claude model: `claude-sonnet-5-5` (named in the approved spec). Call it through `client.beta.messages.create` with `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"`. Check `stop_reason == "refusal"` before reading content. Never use forced `tool_choice` (`any`/`tool` returns 400 on this model). Append `response.content` back unchanged (no history edits).
- Max 25 tool calls per agent run.
- Signature items must be `urn:tag:specialty_dish:place:*` tags or place entity IDs: the only kinds the hackathon API returns heatmaps for (live probe, 2026-10-06).
- Qloo: at most 3 concurrent requests; retry 429 with back-off.
- No playlist/artists anywhere: location-based artist results are megastar-dominated and include unsafe raw entries.
- `QLOO_API_KEY` and `ANTHROPIC_API_KEY` exist only as server environment variables. Never send them to the browser.
- Live-run rate limit: 6 signature/score runs per IP per hour; 30 briefs per IP per hour.
- Copy rules: name the chain only descriptively, never use its logo or colors, and show "Not affiliated with [Chain]" and "Prioritizes which stores to test in. Not a sales forecast." in the UI footer.
- Briefs and reasons may only name tags and entities that Qloo returned.
- Repo: public, MIT `LICENSE` at the root.

## File Structure

```
qloo-hackathon/
├── backend/
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── qloo.py        # HTTP client, disk cache, ALL Qloo response parsing
│   │   ├── stores.py      # load stores.csv
│   │   ├── scoring.py     # pure math: nearest cell, z-scores, pick, spearman, stability
│   │   ├── tools.py       # agent tools over Qloo + stores
│   │   ├── agent.py       # Claude calls: tool loop, signature, scoring run, brief
│   │   └── main.py        # FastAPI routes, SSE, rate limit, demos, static files
│   ├── data/
│   │   ├── stores.csv     # covered Philz stores (Task 11)
│   │   ├── candidates/    # raw + geocoded Philz store lists
│   │   ├── demos/         # precomputed demo runs (Task 12)
│   │   └── cache/         # Qloo response cache (gitignored)
│   ├── scripts/
│   │   ├── geocode.py
│   │   ├── probe_qloo.py
│   │   ├── coverage_check.py
│   │   └── precompute_demos.py
│   └── tests/
│       ├── fixtures/      # raw Qloo responses saved by the probe (Task 10)
│       ├── test_qloo.py
│       ├── test_scoring.py
│       ├── test_tools.py
│       ├── test_agent.py
│       └── test_main.py
├── frontend/
│   ├── package.json, vite.config.js, index.html
│   └── src/
│       ├── main.jsx, App.jsx, api.js, config.js, styles.css
│       ├── MapView.jsx, InputCard.jsx, RankCard.jsx, TraceBar.jsx, StoreDrawer.jsx
├── Dockerfile
├── render.yaml
├── LICENSE
└── README.md
```

**Shared data shapes** (used across tasks, defined once here):

```python
# Store (stores.py)
{"id": "philz-sf-mission", "name": "24th St (Mission)", "address": "3101 24th St, San Francisco, CA",
 "lat": 37.7524, "lon": -122.4148, "metro": "San Francisco"}

# SignatureItem (agent.py output, frontend chips)
{"id": "urn:tag:specialty_dish:place:matcha", "name": "Matcha", "kind": "tag" | "entity", "weight": 0.9,
 "substituted_from": None | "yuzu"}

# Heatmap cell (qloo.parse_heatmap)
{"lat": 40.71, "lon": -73.95, "affinity": 0.82, "popularity": 0.64}

# ScoredStore (scoring.score) = Store + 
{"affinity": float | None, "popularity": float | None, "fit": float | None,
 "confidence": "high" | "low" | "none"}

# Stream events (agent.py -> main.py SSE -> frontend)
{"type": "trace", "tool": "find_tags", "args": {...}, "summary": "3 results: matcha, ..."}
{"type": "signature", "items": [SignatureItem], "dropped": 0}
{"type": "result", "stores": [ScoredStore], "top": [id], "bottom": [id],
 "reasons": {id: str}, "stability": None | {"rho": 0.86, "weakest": "Matcha Latte"}}
{"type": "error", "message": str}

# Brief (agent.write_brief)
{"store_id": id, "fit": float | None, "label": "test" | "maybe" | "skip", "verdict": str,
 "why_tags": [{"id","name","affinity"}], "partners": [{"id","name","affinity","image"}], "menu_cues": [str]}
```

**Order note:** Tasks 1–9 run on fakes and need no API key. Tasks 10–12 need the Qloo key. Task 13 needs both keys.

---

### Task 1: Backend scaffold + Qloo client

**Files:**
- Create: `backend/requirements.txt`, `backend/pytest.ini`, `backend/app/__init__.py`, `backend/app/qloo.py`, `backend/tests/test_qloo.py`, `.gitignore` (modify)

**Interfaces:**
- Produces: `qloo.BASE_URL`, `qloo.MAX_RETRIES`, `qloo.QlooError(status, body)`, `qloo.point(lat, lon) -> str`, `qloo.cache_key(path, params) -> str`, parsers `parse_tag_search`, `parse_search`, `parse_entities`, `parse_area_tags`, `parse_heatmap`, and `class Qloo(api_key, cache_dir, http=None, max_concurrency=3)` with async methods:
  - `get(path, params) -> dict` (retries 429 with back-off)
  - `search_tags(query, take=10) -> list[{"id","name","type"}]`
  - `search_places(query, take=5) -> list[{"id","name","type"}]`
  - `heatmap(item: SignatureItem, metro: str) -> list[cell]`
  - `area_tags(lat, lon, radius_m, take=10) -> list[{"id","name","affinity"}]`
  - `area_places(lat, lon, radius_m, take=5) -> list[{"id","name","affinity","image"}]`

Response shapes in this task were confirmed against the live API on 2026-10-06.

- [ ] **Step 1: Create dependency and test config**

`backend/requirements.txt`:
```
fastapi>=0.115
uvicorn[standard]>=0.30
httpx>=0.27
anthropic>=0.116
pytest>=8
pytest-asyncio>=0.24
```

`backend/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

Append to the root `.gitignore`:
```
backend/data/cache/
__pycache__/
.venv/
node_modules/
frontend/dist/
```

Create an empty `backend/app/__init__.py`.

Run:
```bash
cd backend && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```
Expected: installs without errors.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_qloo.py`:
```python
import httpx
import pytest

from app import qloo
from app.qloo import (BASE_URL, Qloo, QlooError, cache_key, parse_area_tags, parse_entities,
                      parse_heatmap, parse_search, parse_tag_search, point)


def make_client(tmp_path, handler):
    http = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return Qloo("test-key", tmp_path, http=http)


def test_point_is_lon_first():
    assert point(40.7, -73.9) == "POINT(-73.9 40.7)"


def test_cache_key_ignores_param_order():
    assert cache_key("/v2/insights", {"a": 1, "b": 2}) == cache_key("/v2/insights", {"b": 2, "a": 1})


async def test_get_sends_key_and_caches(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"results": {"tags": []}})

    q = make_client(tmp_path, handler)
    await q.get("/v2/tags", {"filter.query": "matcha"})
    await q.get("/v2/tags", {"filter.query": "matcha"})
    assert len(calls) == 1
    assert calls[0].headers["X-Api-Key"] == "test-key"


async def test_errors_raise_and_are_not_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, text="forbidden")

    q = make_client(tmp_path, handler)
    for _ in range(2):
        with pytest.raises(QlooError) as e:
            await q.get("/v2/insights", {"filter.type": "urn:entity:music"})
        assert e.value.status == 403
    assert len(calls) == 2


async def test_heatmap_uses_tags_or_entities_param(tmp_path):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": {"heatmap": []}})

    q = make_client(tmp_path, handler)
    await q.heatmap({"id": "T1", "kind": "tag", "weight": 1}, "Brooklyn")
    await q.heatmap({"id": "E1", "kind": "entity", "weight": 1}, "Brooklyn")
    assert seen[0]["signal.interests.tags"] == "T1"
    assert seen[1]["signal.interests.entities"] == "E1"
    assert seen[0]["filter.type"] == "urn:heatmap"
    assert seen[0]["filter.location.query"] == "Brooklyn"


async def test_area_queries_use_point_location(tmp_path):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": {"entities": [], "tags": []}})

    q = make_client(tmp_path, handler)
    await q.area_places(40.7, -73.9, 1200)
    await q.area_tags(40.7, -73.9, 1200)
    assert seen[0]["filter.type"] == "urn:entity:place"
    assert seen[0]["filter.location"] == "POINT(-73.9 40.7)"
    assert seen[1]["filter.type"] == "urn:tag"
    assert seen[1]["signal.location"] == "POINT(-73.9 40.7)"


async def test_retries_429_then_succeeds(tmp_path, monkeypatch):
    statuses = [429, 429, 200]
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    def handler(request):
        code = statuses.pop(0)
        return httpx.Response(code, json={"results": {"tags": []}}, headers={"retry-after": "1"} if code == 429 else {})

    monkeypatch.setattr(qloo, "_sleep", fake_sleep)
    q = make_client(tmp_path, handler)
    assert await q.get("/v2/tags", {"filter.query": "x"}) == {"results": {"tags": []}}
    assert slept == [1.0, 1.0]


def test_parsers():
    assert parse_tag_search({"results": {"tags": [{"id": "T1", "name": "Matcha", "type": "urn:tag:specialty_dish:place"}]}}) == [
        {"id": "T1", "name": "Matcha", "type": "urn:tag:specialty_dish:place"}]
    assert parse_search({"results": [{"entity_id": "E1", "name": "Cafe", "types": ["urn:entity:place"]}]}) == [
        {"id": "E1", "name": "Cafe", "type": "urn:entity:place"}]
    assert parse_entities({"results": {"entities": [{"entity_id": "E1", "name": "Khruangbin", "query": {"affinity": 0.9},
                                                       "properties": {"image": {"url": "http://img"}}}]}}) == [
        {"id": "E1", "name": "Khruangbin", "affinity": 0.9, "image": "http://img"}]
    assert parse_area_tags({"results": {"tags": [{"tag_id": "T1", "name": "matcha", "query": {"affinity": 0.7}}]}}) == [
        {"id": "T1", "name": "matcha", "affinity": 0.7}]
    assert parse_heatmap({"results": {"heatmap": [{"location": {"latitude": 1.0, "longitude": 2.0},
                                                    "query": {"affinity": 0.5, "popularity": 0.4}}]}}) == [
        {"lat": 1.0, "lon": 2.0, "affinity": 0.5, "popularity": 0.4}]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_qloo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.qloo'`

- [ ] **Step 4: Implement `backend/app/qloo.py`**

```python
"""Thin async Qloo client: disk cache + response parsing. Every Qloo response shape lives in this file."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

BASE_URL = "https://hackathon.api.qloo.com"
MAX_RETRIES = 3
_sleep = asyncio.sleep  # indirection so tests can skip real waits


class QlooError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Qloo {status}: {body[:200]}")
        self.status = status


def point(lat: float, lon: float) -> str:
    return f"POINT({lon} {lat})"  # WKT is lon-first


def cache_key(path: str, params: dict) -> str:
    raw = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1(raw.encode()).hexdigest()


def parse_tag_search(resp: dict) -> list[dict]:
    return [{"id": t["id"], "name": t["name"], "type": t.get("type")}
            for t in resp.get("results", {}).get("tags", [])]


def parse_search(resp: dict) -> list[dict]:
    return [{"id": e["entity_id"], "name": e["name"], "type": (e.get("types") or [None])[0]}
            for e in resp.get("results", [])]


def parse_entities(resp: dict) -> list[dict]:
    out = []
    for e in resp.get("results", {}).get("entities", []):
        props = e.get("properties") or {}
        out.append({"id": e["entity_id"], "name": e["name"],
                    "affinity": (e.get("query") or {}).get("affinity"),
                    "image": (props.get("image") or {}).get("url")})
    return out


def parse_area_tags(resp: dict) -> list[dict]:
    return [{"id": t.get("tag_id") or t.get("id"), "name": t["name"],
             "affinity": (t.get("query") or {}).get("affinity")}
            for t in resp.get("results", {}).get("tags", [])]


def parse_heatmap(resp: dict) -> list[dict]:
    return [{"lat": c["location"]["latitude"], "lon": c["location"]["longitude"],
             "affinity": c["query"]["affinity"], "popularity": c["query"].get("popularity", 0.0)}
            for c in resp.get("results", {}).get("heatmap", [])]


class Qloo:
    def __init__(self, api_key: str, cache_dir: Path, http: httpx.AsyncClient | None = None,
                 max_concurrency: int = 3):  # the hackathon API returns 429 under bursts
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http = http or httpx.AsyncClient(base_url=BASE_URL, timeout=60)
        self.sem = asyncio.Semaphore(max_concurrency)

    async def get(self, path: str, params: dict) -> dict:
        f = self.cache_dir / f"{cache_key(path, params)}.json"
        if f.exists():
            return json.loads(f.read_text())
        for attempt in range(MAX_RETRIES + 1):
            async with self.sem:
                r = await self.http.get(path, params=params, headers={"X-Api-Key": self.api_key})
            if r.status_code != 429 or attempt == MAX_RETRIES:
                break
            await _sleep(float(r.headers.get("retry-after", 2 ** (attempt + 1))))
        if r.status_code != 200:
            raise QlooError(r.status_code, r.text)
        data = r.json()
        f.write_text(json.dumps(data))
        return data

    async def search_tags(self, query: str, take: int = 10) -> list[dict]:
        return parse_tag_search(await self.get("/v2/tags", {"filter.query": query, "take": take}))

    async def search_places(self, query: str, take: int = 5) -> list[dict]:
        return parse_search(await self.get("/search", {"query": query, "types": "urn:entity:place", "take": take}))

    async def heatmap(self, item: dict, metro: str) -> list[dict]:
        key = "signal.interests.tags" if item["kind"] == "tag" else "signal.interests.entities"
        return parse_heatmap(await self.get("/v2/insights", {
            "filter.type": "urn:heatmap", "filter.location.query": metro, key: item["id"]}))

    async def area_tags(self, lat: float, lon: float, radius_m: int, take: int = 10) -> list[dict]:
        return parse_area_tags(await self.get("/v2/insights", {
            "filter.type": "urn:tag", "signal.location": point(lat, lon),
            "signal.location.radius": radius_m, "take": take}))

    async def area_places(self, lat: float, lon: float, radius_m: int, take: int = 5) -> list[dict]:
        return parse_entities(await self.get("/v2/insights", {
            "filter.type": "urn:entity:place", "filter.location": point(lat, lon),
            "filter.location.radius": radius_m, "take": take}))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_qloo.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add .gitignore backend/requirements.txt backend/pytest.ini backend/app/__init__.py backend/app/qloo.py backend/tests/test_qloo.py
git commit -m "feat: Qloo client with disk cache and response parsers"
```

---

### Task 2: Store loading + geocoding script

**Files:**
- Create: `backend/app/stores.py`, `backend/scripts/geocode.py`, `backend/data/stores.csv` (placeholder sample), `backend/tests/test_stores.py`

**Interfaces:**
- Produces: `stores.load_stores(path) -> list[Store]`. CSV columns: `id,name,address,lat,lon,metro`.
- `scripts/geocode.py IN.csv OUT.csv` reads `id,name,address,metro` and writes the same columns plus `lat,lon`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_stores.py`:
```python
from app.stores import load_stores


def test_load_stores(tmp_path):
    f = tmp_path / "stores.csv"
    f.write_text("id,name,address,lat,lon,metro\n"
                 "phl-1,Rittenhouse,130 S 19th St,39.95,-75.17,Philadelphia\n")
    assert load_stores(f) == [{"id": "phl-1", "name": "Rittenhouse", "address": "130 S 19th St",
                               "lat": 39.95, "lon": -75.17, "metro": "Philadelphia"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_stores.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.stores'`

- [ ] **Step 3: Implement `backend/app/stores.py`**

```python
import csv
from pathlib import Path


def load_stores(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return [{"id": r["id"], "name": r["name"], "address": r["address"],
                 "lat": float(r["lat"]), "lon": float(r["lon"]), "metro": r["metro"]}
                for r in csv.DictReader(f)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_stores.py -v`
Expected: 1 passed

- [ ] **Step 5: Write `backend/scripts/geocode.py`**

```python
"""Add lat/lon to a store CSV using OpenStreetMap Nominatim (free; 1 request/second policy).

Usage: python scripts/geocode.py data/candidates/raw/philz.csv data/candidates/philz.csv
Input columns: id,name,address,metro. Rows that fail to geocode are printed and skipped.
"""
import csv
import sys
import time

import httpx

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "tastetest-hackathon/0.1 (store geocoding)"}


def main(src: str, dst: str) -> None:
    with open(src, newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        resp = httpx.get(URL, params={"q": r["address"], "format": "json", "limit": 1}, headers=HEADERS, timeout=20)
        hits = resp.json() if resp.status_code == 200 else []
        if hits:
            out.append({**r, "lat": hits[0]["lat"], "lon": hits[0]["lon"]})
        else:
            print(f"SKIPPED (no match): {r['id']} {r['address']}")
        time.sleep(1.1)  # Nominatim usage policy
    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "address", "lat", "lon", "metro"])
        w.writeheader()
        w.writerows({k: row[k] for k in w.fieldnames} for row in out)
    print(f"wrote {len(out)}/{len(rows)} stores to {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

- [ ] **Step 6: Create a placeholder `backend/data/stores.csv`**

This file is used for local development until Task 11 replaces it with the chosen chain. It contains 6 neighborhoods in 2 metros so the UI has something to show:
```
id,name,address,lat,lon,metro
nyc-williamsburg,Williamsburg,N 6th St & Wythe Ave Brooklyn NY,40.7193,-73.9590,New York
nyc-midtown-east,Midtown East,E 52nd St & 3rd Ave New York NY,40.7572,-73.9693,New York
nyc-west-village,West Village,Bleecker St & Christopher St New York NY,40.7335,-74.0040,New York
la-silver-lake,Silver Lake,Sunset Blvd & Sanborn Ave Los Angeles CA,34.0912,-118.2790,Los Angeles
la-century-city,Century City,Santa Monica Blvd & Ave of the Stars Los Angeles CA,34.0590,-118.4170,Los Angeles
la-arts-district,Arts District,E 3rd St & Traction Ave Los Angeles CA,34.0470,-118.2350,Los Angeles
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/stores.py backend/scripts/geocode.py backend/data/stores.csv backend/tests/test_stores.py
git commit -m "feat: store CSV loader, geocoding script, placeholder stores"
```

---

### Task 3: Scoring math

**Files:**
- Create: `backend/app/scoring.py`, `backend/tests/test_scoring.py`

**Interfaces:**
- Consumes: Store, heatmap cell shapes (see Shared data shapes).
- Produces:
  - `km(lat1, lon1, lat2, lon2) -> float`
  - `nearest_cell(cells, lat, lon, max_km=MAX_CELL_KM) -> cell | None`
  - `score(stores, cells_by_metro: dict[metro, dict[item_id, list[cell]]], weights: dict[item_id, float]) -> list[ScoredStore]`, sorted by fit descending with unscored stores last
  - `pick(scored, top_n=5, bottom_n=3) -> (top: list[ScoredStore], bottom: list[ScoredStore])`, with bottom ordered worst first and no overlap with top
  - `spearman(a: list[float], b: list[float]) -> float | None`, using average ranks for ties; `None` if fewer than 3 points or a constant series
  - `stability(stores, cells_by_metro, weights) -> {"rho": float, "weakest": item_id} | None`: leave-one-out over items, reporting the minimum ρ; `None` if there are fewer than 2 items
  - Constants `MAX_CELL_KM = 1.5`, `MIN_POPULARITY = 0.2`

**Missing-data rule** (from the live probe: heatmap cells are sparse and only appear where there's signal):
- The city has cells for an item, but none within `MAX_CELL_KM` of the store → that item contributes affinity 0 and popularity 0. No signal nearby means low interest.
- The city has no cells for an item → the item is skipped for that store.
- No usable items → `fit=None`, `confidence="none"`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_scoring.py`:
```python
import pytest

from app.scoring import km, nearest_cell, pick, score, spearman, stability


def store(id, lat, lon, metro="M"):
    return {"id": id, "name": id, "address": "", "lat": lat, "lon": lon, "metro": metro}


def cell(lat, lon, affinity, popularity=0.9):
    return {"lat": lat, "lon": lon, "affinity": affinity, "popularity": popularity}


def test_km_one_degree_latitude():
    assert round(km(0, 0, 1, 0)) == 111


def test_nearest_cell_picks_closest_and_respects_max():
    cells = [cell(40.0, -74.0, 0.1), cell(40.01, -74.0, 0.9)]
    assert nearest_cell(cells, 40.009, -74.0)["affinity"] == 0.9
    assert nearest_cell(cells, 40.05, -74.0) is None  # ~4.4 km away
    assert nearest_cell([], 40.0, -74.0) is None


def test_score_z_scores_and_sorts():
    stores = [store("lo", 0.0, 0.2), store("hi", 0.0, 0.0), store("mid", 0.0, 0.1)]
    cells = {"M": {"T1": [cell(0.0, 0.0, 0.9), cell(0.0, 0.1, 0.5), cell(0.0, 0.2, 0.1)]}}
    out = score(stores, cells, {"T1": 1.0})
    assert [s["id"] for s in out] == ["hi", "mid", "lo"]
    assert [s["fit"] for s in out] == [1.22, 0.0, -1.22]
    assert all(s["confidence"] == "high" for s in out)


def test_score_weighted_mean_across_items():
    stores = [store("a", 0.0, 0.0), store("b", 0.0, 0.1)]
    cells = {"M": {"T1": [cell(0.0, 0.0, 1.0), cell(0.0, 0.1, 0.0)],
                   "T2": [cell(0.0, 0.0, 0.0), cell(0.0, 0.1, 1.0)]}}
    by_id = {s["id"]: s for s in score(stores, cells, {"T1": 3.0, "T2": 1.0})}
    assert by_id["a"]["affinity"] == 0.75
    assert by_id["b"]["affinity"] == 0.25


def test_missing_data_rules():
    stores = [store("a", 0.0, 0.0), store("b", 0.0, 0.1), store("far", 10.0, 10.0),
              store("nodata", 0.0, 0.0, metro="M2")]
    cells = {"M": {"T1": [cell(0.0, 0.0, 0.9, popularity=0.1), cell(0.0, 0.1, 0.5)]}}
    by_id = {s["id"]: s for s in score(stores, cells, {"T1": 1.0})}
    assert by_id["far"]["affinity"] == 0.0 and by_id["far"]["confidence"] == "low"  # city has data, none nearby
    assert by_id["nodata"]["fit"] is None and by_id["nodata"]["confidence"] == "none"  # city has no data
    assert by_id["a"]["confidence"] == "low"  # popularity below MIN_POPULARITY
    out = score(stores, cells, {"T1": 1.0})
    assert [s["id"] for s in out] == ["a", "b", "far", "nodata"]


def test_item_without_city_data_is_skipped_not_penalized():
    stores = [store("a", 0.0, 0.0), store("b", 0.0, 0.1)]
    cells = {"M": {"T1": [cell(0.0, 0.0, 0.8), cell(0.0, 0.1, 0.4)], "T2": []}}
    by_id = {s["id"]: s for s in score(stores, cells, {"T1": 1.0, "T2": 1.0})}
    assert by_id["a"]["affinity"] == 0.8


def test_single_scored_store_gets_zero_fit():
    out = score([store("a", 0.0, 0.0)], {"M": {"T1": [cell(0.0, 0.0, 0.5)]}}, {"T1": 1.0})
    assert out[0]["fit"] == 0.0


def test_pick_no_overlap_and_bottom_worst_first():
    scored = [{"id": str(i), "fit": f} for i, f in enumerate([2.0, 1.0, 0.5, 0.0, -0.5, -1.0])]
    top, bottom = pick(scored)
    assert [s["id"] for s in top] == ["0", "1", "2", "3", "4"]
    assert [s["id"] for s in bottom] == ["5"]
    scored.append({"id": "x", "fit": None})
    top, bottom = pick(scored, top_n=2, bottom_n=2)
    assert [s["id"] for s in bottom] == ["5", "4"]


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(0.866, abs=1e-3)  # ties get average ranks
    assert spearman([1, 2], [1, 2]) is None
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def four_stores():
    return [store(f"s{i}", 0.0, i * 0.1) for i in range(4)]


def cells_for(affinities):
    return [cell(0.0, i * 0.1, a) for i, a in enumerate(affinities)]


def test_stability_agreeing_items_is_one():
    cells = {"M": {"T1": cells_for([0.9, 0.7, 0.5, 0.3]), "T2": cells_for([0.8, 0.6, 0.4, 0.2])}}
    assert stability(four_stores(), cells, {"T1": 1.0, "T2": 1.0}) == {"rho": 1.0, "weakest": "T1"}


def test_stability_finds_the_item_the_ranking_hangs_on():
    cells = {"M": {"T1": cells_for([0.9, 0.7, 0.5, 0.3]), "T2": cells_for([0.1, 0.3, 0.5, 0.7])}}
    assert stability(four_stores(), cells, {"T1": 1.0, "T2": 0.5}) == {"rho": -1.0, "weakest": "T1"}


def test_stability_needs_two_items():
    assert stability(four_stores(), {"M": {"T1": cells_for([0.9, 0.7, 0.5, 0.3])}}, {"T1": 1.0}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scoring'`

- [ ] **Step 3: Implement `backend/app/scoring.py`**

```python
"""Pure scoring math. No I/O; everything here is unit-tested."""
import math
from statistics import mean, pstdev

# Calibrated on live hackathon heatmaps (2026-10-06): cells sit ~0.2-0.8 km apart; popularity p25 ~0.23.
MAX_CELL_KM = 1.5
MIN_POPULARITY = 0.2


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def nearest_cell(cells: list[dict], lat: float, lon: float, max_km: float = MAX_CELL_KM) -> dict | None:
    if not cells:
        return None
    best = min(cells, key=lambda c: km(lat, lon, c["lat"], c["lon"]))
    return best if km(lat, lon, best["lat"], best["lon"]) <= max_km else None


def _store_affinity(store: dict, cells_by_item: dict, weights: dict) -> tuple[float | None, float | None]:
    hits = []  # (weight, affinity, popularity)
    for item_id, cells in cells_by_item.items():
        if not cells:
            continue  # the city has no data for this item: skip it rather than penalize the store
        c = nearest_cell(cells, store["lat"], store["lon"])
        # Cells only exist where there's signal, so none nearby (in a city with data) means low interest.
        hits.append((weights[item_id], c["affinity"], c["popularity"]) if c else (weights[item_id], 0.0, 0.0))
    total = sum(w for w, _, _ in hits)
    if total == 0:
        return None, None
    return sum(w * a for w, a, _ in hits) / total, mean(p for _, _, p in hits)


def score(stores: list[dict], cells_by_metro: dict, weights: dict) -> list[dict]:
    rows = []
    for s in stores:
        aff, pop = _store_affinity(s, cells_by_metro.get(s["metro"], {}), weights)
        rows.append({**s, "affinity": aff, "popularity": pop})
    vals = [r["affinity"] for r in rows if r["affinity"] is not None]
    mu = mean(vals) if vals else 0.0
    sd = pstdev(vals) if len(vals) > 1 else 0.0
    for r in rows:
        if r["affinity"] is None:
            r["fit"], r["confidence"] = None, "none"
        else:
            r["fit"] = round((r["affinity"] - mu) / sd, 2) if sd else 0.0
            r["confidence"] = "high" if r["popularity"] >= MIN_POPULARITY else "low"
    return sorted(rows, key=lambda r: (r["fit"] is None, -(r["fit"] or 0)))


def pick(scored: list[dict], top_n: int = 5, bottom_n: int = 3) -> tuple[list[dict], list[dict]]:
    ranked = [s for s in scored if s["fit"] is not None]
    top = ranked[:top_n]
    bottom = [s for s in reversed(ranked[-bottom_n:]) if s not in top]
    return top, bottom


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1  # ties share the average rank
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    sa, sb = pstdev(ra), pstdev(rb)
    if sa == 0 or sb == 0:
        return None
    ma, mb = mean(ra), mean(rb)
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (len(ra) * sa * sb)


def stability(stores: list[dict], cells_by_metro: dict, weights: dict) -> dict | None:
    """Leave-one-out: how much does the ranking move when any single concept is dropped? Reports the worst case."""
    if len(weights) < 2:
        return None
    full = {s["id"]: s["fit"] for s in score(stores, cells_by_metro, weights)}
    worst = None
    for item_id in weights:
        w2 = {k: v for k, v in weights.items() if k != item_id}
        c2 = {m: {k: v for k, v in items.items() if k != item_id} for m, items in cells_by_metro.items()}
        reduced = {s["id"]: s["fit"] for s in score(stores, c2, w2)}
        ids = [i for i in full if full[i] is not None and reduced.get(i) is not None]
        rho = spearman([full[i] for i in ids], [reduced[i] for i in ids])
        if rho is not None and (worst is None or rho < worst[0]):
            worst = (rho, item_id)
    return {"rho": round(worst[0], 2), "weakest": worst[1]} if worst else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_scoring.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring.py backend/tests/test_scoring.py
git commit -m "feat: store fit scoring with sparse-cell rules and leave-one-out stability"
```

---

### Task 4: Agent tools

**Files:**
- Create: `backend/app/tools.py`, `backend/tests/test_tools.py`

**Interfaces:**
- Consumes: `Qloo` methods from Task 1, `score`/`stability` from Task 3, the Store list from Task 2.
- Produces: `RADIUS_M = 1200`, `HEATMAP_TAG_PREFIX = "urn:tag:specialty_dish:place:"`, and `class Tools(qloo, stores)` with:
  - `store(store_id) -> Store` (raises `KeyError` if the id is unknown)
  - `async find_tags(query) -> list[{"id","name","type"}]` (only heatmap-capable specialty-dish tags)
  - `async find_places(query) -> list[{"id","name","type"}]`
  - `async score_stores(signature: list[SignatureItem]) -> {"stores": list[ScoredStore], "stability": {"rho","weakest"} | None}`
  - `async area_taste(store_id) -> {"tags": [...], "places": [...]}`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tools.py`:
```python
import pytest

from app.qloo import QlooError
from app.tools import Tools

STORES = [
    {"id": "a", "name": "A", "address": "", "lat": 0.0, "lon": 0.0, "metro": "M1"},
    {"id": "b", "name": "B", "address": "", "lat": 0.0, "lon": 0.1, "metro": "M1"},
    {"id": "c", "name": "C", "address": "", "lat": 5.0, "lon": 5.0, "metro": "M2"},
]


class FakeQloo:
    def __init__(self, fail_metro=None):
        self.heatmap_calls = []
        self.fail_metro = fail_metro

    async def search_tags(self, query, take=10):
        return [{"id": "urn:tag:specialty_dish:place:matcha", "name": "Matcha", "type": "urn:tag:specialty_dish:place"},
                {"id": "urn:tag:menu_highlight:qloo:matcha", "name": "Matcha", "type": "urn:tag:menu_highlight:qloo"}]

    async def heatmap(self, item, metro):
        self.heatmap_calls.append((item["id"], metro))
        if metro == self.fail_metro:
            raise QlooError(500, "boom")
        return {"M1": [{"lat": 0.0, "lon": 0.0, "affinity": 0.9, "popularity": 0.9},
                       {"lat": 0.0, "lon": 0.1, "affinity": 0.1, "popularity": 0.9}],
                "M2": [{"lat": 5.0, "lon": 5.0, "affinity": 0.5, "popularity": 0.9}]}[metro]

    async def area_tags(self, lat, lon, radius_m, take=10):
        return [{"id": "T1", "name": "Foodies", "affinity": 0.8}]

    async def area_places(self, lat, lon, radius_m, take=5):
        raise QlooError(429, "slow down")


SIG = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None},
       {"id": "T0", "name": "dropped", "kind": "tag", "weight": 0.0, "substituted_from": None}]


async def test_find_tags_keeps_only_heatmap_capable_tags():
    tags = await Tools(FakeQloo(), STORES).find_tags("matcha")
    assert [t["id"] for t in tags] == ["urn:tag:specialty_dish:place:matcha"]


async def test_score_stores_one_heatmap_per_metro_and_weighted_item():
    q = FakeQloo()
    out = await Tools(q, STORES).score_stores(SIG)
    assert sorted(q.heatmap_calls) == [("T1", "M1"), ("T1", "M2")]
    assert [s["id"] for s in out["stores"]] == ["a", "c", "b"]
    assert out["stability"] is None  # only one weighted item


async def test_score_stores_survives_one_failed_metro():
    out = await Tools(FakeQloo(fail_metro="M2"), STORES).score_stores(SIG)
    assert {s["id"]: s["confidence"] for s in out["stores"]}["c"] == "none"


async def test_area_taste_tolerates_partial_failure():
    taste = await Tools(FakeQloo(), STORES).area_taste("a")
    assert taste == {"tags": [{"id": "T1", "name": "Foodies", "affinity": 0.8}], "places": []}


def test_unknown_store_raises_keyerror():
    with pytest.raises(KeyError):
        Tools(FakeQloo(), STORES).store("nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools'`

- [ ] **Step 3: Implement `backend/app/tools.py`**

```python
"""The agent's tools: thin wrappers over Qloo + the store list."""
import asyncio

from .scoring import score, stability

RADIUS_M = 1200
# The only tag type the hackathon API returns heatmaps for (live probe, 2026-10-06).
HEATMAP_TAG_PREFIX = "urn:tag:specialty_dish:place:"


class Tools:
    def __init__(self, qloo, stores: list[dict]):
        self.qloo = qloo
        self.stores = stores
        self._by_id = {s["id"]: s for s in stores}

    def store(self, store_id: str) -> dict:
        return self._by_id[store_id]

    async def find_tags(self, query: str) -> list[dict]:
        return [t for t in await self.qloo.search_tags(query) if t["id"].startswith(HEATMAP_TAG_PREFIX)]

    async def find_places(self, query: str) -> list[dict]:
        return await self.qloo.search_places(query)

    async def score_stores(self, signature: list[dict]) -> dict:
        items = [i for i in signature if i["weight"] > 0]
        metros = sorted({s["metro"] for s in self.stores})
        pairs = [(m, i) for m in metros for i in items]
        results = await asyncio.gather(*(self.qloo.heatmap(i, m) for m, i in pairs), return_exceptions=True)
        if results and all(isinstance(r, Exception) for r in results):
            raise results[0]
        by_metro = {m: {} for m in metros}
        for (m, i), cells in zip(pairs, results):
            by_metro[m][i["id"]] = [] if isinstance(cells, Exception) else cells
        weights = {i["id"]: i["weight"] for i in items}
        return {"stores": score(self.stores, by_metro, weights), "stability": stability(self.stores, by_metro, weights)}

    async def area_taste(self, store_id: str) -> dict:
        s = self.store(store_id)
        parts = await asyncio.gather(self.qloo.area_tags(s["lat"], s["lon"], RADIUS_M),
                                     self.qloo.area_places(s["lat"], s["lon"], RADIUS_M), return_exceptions=True)
        tags, places = [[] if isinstance(p, Exception) else p for p in parts]
        return {"tags": tags, "places": places}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_tools.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools.py backend/tests/test_tools.py
git commit -m "feat: agent tools over Qloo (dish tags, places, scoring with stability, area taste)"
```

---

### Task 5: Agent (Claude tool loop, signature, scoring run, brief)

**Files:**
- Create: `backend/app/agent.py`, `backend/tests/test_agent.py`

**Interfaces:**
- Consumes: `Tools` (Task 4: `find_tags`, `find_places`, `score_stores` → `{"stores","stability"}`, `area_taste` → `{"tags","places"}`), `pick` (Task 3), `QlooError` (Task 1). The `llm` argument is an `anthropic.AsyncAnthropic` instance, or a fake with the same `llm.beta.messages.create(**kw)` coroutine.
- Produces:
  - `MODEL = "claude-sonnet-5-5"`, `MAX_TOOL_CALLS = 25`, `class AgentError(Exception)`
  - `async run_tool_loop(llm, *, system, user, tools, handlers, finish_tool, max_calls=MAX_TOOL_CALLS)`, an async generator of trace events that ends with `{"type": "finish", "input": dict}`
  - `async build_signature(llm, tools: Tools, lto, current=None, instruction=None)`, an async generator of trace events that ends with a `signature` event
  - `async run_score(llm, tools: Tools, signature)`, an async generator of trace events that ends with a `result` event
  - `async write_brief(llm, tools: Tools, store_id, signature, fit) -> Brief`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_agent.py`:
```python
import json
from types import SimpleNamespace as NS

import pytest

from app import agent
from app.agent import AgentError, build_signature, run_score, run_tool_loop, write_brief


def tool_use(id, name, input):
    return NS(type="tool_use", id=id, name=name, input=input)


def text(t):
    return NS(type="text", text=t)


def resp(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop)


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    async def _create(self, **kw):
        # Snapshot messages: the loop keeps appending to the same list after this call returns.
        self.calls.append({**kw, "messages": list(kw.get("messages", []))})
        return self.responses.pop(0)


class FakeTools:
    stores = [{"id": s, "name": s, "address": "", "lat": 0, "lon": 0, "metro": "M"} for s in "abcd"]

    async def find_tags(self, query):
        return [{"id": "T-" + query, "name": query}]

    async def find_places(self, query):
        return []

    async def score_stores(self, signature):
        fits = {"a": 1.5, "b": 0.5, "c": -0.5, "d": -1.5}
        return {"stores": [{**s, "fit": fits[s["id"]], "confidence": "high"} for s in self.stores],
                "stability": {"rho": 0.86, "weakest": "T1"}}

    async def area_taste(self, store_id):
        return {"tags": [{"id": "T9", "name": "japanese cafe", "affinity": 0.9}],
                "places": [{"id": "P1", "name": "Tea Shop", "affinity": 0.8, "image": None}]}

    def store(self, store_id):
        return next(s for s in self.stores if s["id"] == store_id)


async def collect(gen):
    return [ev async for ev in gen]


async def test_build_signature_drops_invented_ids():
    llm = FakeLLM([
        resp(tool_use("t1", "find_tags", {"query": "matcha"})),
        resp(tool_use("t2", "submit_signature", {"items": [
            {"id": "T-matcha", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None},
            {"id": "T-invented", "name": "fake", "kind": "tag", "weight": 0.5, "substituted_from": None}]})),
    ])
    events = await collect(build_signature(llm, FakeTools(), "matcha latte"))
    assert events[0]["type"] == "trace" and events[0]["tool"] == "find_tags"
    assert events[-1] == {"type": "signature", "dropped": 1, "items": [
        {"id": "T-matcha", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]}
    assert llm.calls[0]["model"] == "claude-sonnet-5-5"
    assert llm.calls[0]["fallbacks"] == "default"
    assert "tool_choice" not in llm.calls[0]


async def test_refinement_keeps_current_ids():
    current = [{"id": "T-old", "name": "old", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    llm = FakeLLM([resp(tool_use("t1", "submit_signature", {"items": current}))])
    events = await collect(build_signature(llm, FakeTools(), "x", current=current, instruction="keep it"))
    assert events[-1]["items"] == current


async def test_tool_errors_are_reported_back_and_loop_continues():
    async def boom(query):
        raise TypeError("bad args")

    llm = FakeLLM([resp(tool_use("t1", "find_tags", {"query": "x"})),
                   resp(tool_use("t2", "done", {"ok": True}))])
    events = await collect(run_tool_loop(llm, system="s", user="u", tools=[], handlers={"find_tags": boom},
                                         finish_tool="done"))
    assert events[0]["summary"].startswith("error")
    tool_result = llm.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert events[-1] == {"type": "finish", "input": {"ok": True}}


async def test_tool_call_cap():
    async def find(query):
        return []

    llm = FakeLLM([resp(tool_use(f"t{i}", "find_tags", {"query": "x"})) for i in range(5)])
    with pytest.raises(AgentError, match="cap"):
        await collect(run_tool_loop(llm, system="s", user="u", tools=[], handlers={"find_tags": find},
                                    finish_tool="done", max_calls=2))


async def test_refusal_raises():
    llm = FakeLLM([resp(text("no"), stop="refusal")])
    with pytest.raises(AgentError, match="declined"):
        await collect(build_signature(llm, FakeTools(), "x"))


async def test_stopping_without_finish_raises():
    llm = FakeLLM([resp(text("I am done"), stop="end_turn")])
    with pytest.raises(AgentError, match="submit_signature"):
        await collect(build_signature(llm, FakeTools(), "x"))


async def test_run_score_result_event():
    reasons = {"reasons": [{"store_id": "a", "reason": "Leans into japanese cafe culture."}]}
    llm = FakeLLM([resp(text(json.dumps(reasons)), stop="end_turn")])
    sig = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    events = await collect(run_score(llm, FakeTools(), sig))
    result = events[-1]
    assert result["type"] == "result"
    assert result["top"] == ["a", "b", "c", "d"]  # 4 stores: all fit in the top 5
    assert result["bottom"] == []
    assert result["reasons"]["a"] == "Leans into japanese cafe culture."
    assert result["reasons"]["d"] == "Over-indexes on japanese cafe."  # deterministic fallback
    assert result["stability"] == {"rho": 0.86, "weakest": "matcha"}  # item id mapped to its name
    assert any(e["type"] == "trace" and e["tool"] == "score_stores" for e in events)


async def test_run_score_skip_group_and_no_stability():
    class EightStores(FakeTools):
        stores = [{"id": s, "name": s, "address": "", "lat": 0, "lon": 0, "metro": "M"} for s in "abcdefgh"]

        async def score_stores(self, signature):
            return {"stores": [{**s, "fit": 2.0 - i * 0.5, "confidence": "high"} for i, s in enumerate(self.stores)],
                    "stability": None}

    llm = FakeLLM([resp(text(json.dumps({"reasons": []})), stop="end_turn")])
    sig = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    result = (await collect(run_score(llm, EightStores(), sig)))[-1]
    assert result["bottom"] == ["h", "g", "f"]
    assert result["stability"] is None


async def test_run_score_reason_fallback_when_llm_fails():
    llm = FakeLLM([resp(text("no"), stop="refusal")])
    sig = [{"id": "E1", "name": "Some Brand", "kind": "entity", "weight": 1.0, "substituted_from": None}]
    events = await collect(run_score(llm, FakeTools(), sig))
    assert events[-1]["reasons"]["a"] == "Over-indexes on japanese cafe."


async def test_write_brief_uses_only_qloo_entities():
    out = {"verdict": "The neighborhood leans into Japanese cafe culture.", "menu_cues": ["Lead with matcha"]}
    llm = FakeLLM([resp(text(json.dumps(out)), stop="end_turn")])
    sig = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    brief = await write_brief(llm, FakeTools(), "a", sig, 1.5)
    assert brief["label"] == "test"
    assert "artists" not in brief  # no playlist: location-based artists aren't demo-safe
    assert brief["partners"][0]["name"] == "Tea Shop"
    assert brief["verdict"].startswith("The neighborhood")
    assert brief["menu_cues"] == ["Lead with matcha"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent'` (or `ImportError`)

- [ ] **Step 3: Implement `backend/app/agent.py`**

```python
"""Claude-side logic. The LLM picks Qloo concepts and writes prose; scores come from deterministic code."""
import asyncio
import json

from .qloo import QlooError
from .scoring import pick

MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_CALLS = 25


class AgentError(Exception):
    pass


def trace(tool: str, args: dict, summary: str) -> dict:
    return {"type": "trace", "tool": tool, "args": args, "summary": summary}


def _summarize(out) -> str:
    if isinstance(out, list):
        names = [o.get("name", "?") for o in out[:3] if isinstance(o, dict)]
        return f"{len(out)} results" + (": " + ", ".join(names) if names else "")
    return str(out)[:120]


async def create(llm, *, output_config: dict | None = None, **kw):
    resp = await llm.beta.messages.create(
        model=MODEL, max_tokens=16000, betas=[FALLBACK_BETA], fallbacks="default",
        output_config={"effort": "medium", **(output_config or {})}, **kw)
    if resp.stop_reason == "refusal":
        raise AgentError("the model declined this request")
    return resp


def _text(resp) -> str:
    t = next((b.text for b in resp.content if b.type == "text"), None)
    if t is None:
        raise AgentError("model returned no text")
    return t


async def run_tool_loop(llm, *, system: str, user: str, tools: list, handlers: dict, finish_tool: str,
                        max_calls: int = MAX_TOOL_CALLS):
    messages = [{"role": "user", "content": user}]
    calls = 0
    while True:
        resp = await create(llm, system=system, tools=tools, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            raise AgentError(f"agent stopped without calling {finish_tool}")
        results = []
        for u in uses:
            if u.name == finish_tool:
                yield {"type": "finish", "input": u.input}
                return
            calls += 1
            if calls > max_calls:
                raise AgentError(f"hit the {max_calls}-call cap")
            try:
                out = await handlers[u.name](**u.input)
                summary, is_error = _summarize(out), False
            except (QlooError, KeyError, TypeError) as e:
                out, summary, is_error = {"error": str(e)}, f"error: {e}", True
            yield trace(u.name, u.input, summary)
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out),
                            "is_error": is_error})
        messages.append({"role": "user", "content": results})


# --- Taste signature -------------------------------------------------------------------------

SIGNATURE_SYSTEM = """You turn a coffee chain's limited-time offer (LTO) description into a Qloo taste signature.

1. Break the description into 3-8 concepts that are dishes, drinks, or ingredients (e.g. "matcha latte", "yuzu", "cold brew"). Express the vibe of the target customer through such items or through a well-known place that embodies it.
2. Resolve every concept to a real Qloo ID with find_tags (preferred; it only returns dish and drink tags) or find_places. If a search returns nothing useful, try a broader or synonymous term and put the original word in substituted_from.
3. Weight each item from 0.1 to 1.0 by how central it is to the product.
4. Finish by calling submit_signature exactly once, using only IDs that a search returned. Never invent IDs.

If you are given a current signature and an instruction, edit the signature to satisfy the instruction (search for new concepts as needed) and submit the full updated signature."""

_STR = {"type": "string"}
SIGNATURE_TOOLS = [
    {"name": "find_tags", "strict": True,
     "description": "Search Qloo tags (flavors, cuisines, genres, styles, scenes) by keyword. Returns [{id, name}].",
     "input_schema": {"type": "object", "properties": {"query": _STR}, "required": ["query"],
                      "additionalProperties": False}},
    {"name": "find_places", "strict": True,
     "description": "Search Qloo places (cafes, restaurants, shops) by name. Returns [{id, name, type}].",
     "input_schema": {"type": "object", "properties": {"query": _STR}, "required": ["query"],
                      "additionalProperties": False}},
    {"name": "submit_signature", "strict": True,
     "description": "Submit the final taste signature. Call exactly once, as the last step.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {
         "type": "object", "properties": {
             "id": _STR, "name": _STR, "kind": {"type": "string", "enum": ["tag", "entity"]},
             "weight": {"type": "number"}, "substituted_from": {"type": ["string", "null"]}},
         "required": ["id", "name", "kind", "weight", "substituted_from"], "additionalProperties": False}}},
         "required": ["items"], "additionalProperties": False}},
]


async def build_signature(llm, tools, lto: str, current: list | None = None, instruction: str | None = None):
    seen = {i["id"] for i in current or []}

    async def find_tags(query):
        out = await tools.find_tags(query)
        seen.update(o["id"] for o in out)
        return out

    async def find_places(query):
        out = await tools.find_places(query)
        seen.update(o["id"] for o in out)
        return out

    user = f"LTO: {lto}"
    if current:
        user += f"\n\nCurrent signature: {json.dumps(current)}\nInstruction: {instruction}"

    async for ev in run_tool_loop(llm, system=SIGNATURE_SYSTEM, user=user, tools=SIGNATURE_TOOLS,
                                  handlers={"find_tags": find_tags, "find_places": find_places},
                                  finish_tool="submit_signature"):
        if ev["type"] != "finish":
            yield ev
            continue
        submitted = ev["input"]["items"]
        items = [{**i, "weight": min(1.0, max(0.0, float(i["weight"])))} for i in submitted if i["id"] in seen]
        if not items:
            raise AgentError("no usable Qloo concepts found for this description")
        yield {"type": "signature", "items": items, "dropped": len(submitted) - len(items)}


# --- Scoring run -----------------------------------------------------------------------------

REASONS_SYSTEM = """You explain why each coffee store is a good or bad place to test a new limited-time offer.
For each store, write one sentence of at most 20 words. Cite only tag names from that store's evidence list.
Do not state any taste fact that is not in the evidence."""

REASONS_FORMAT = {"type": "json_schema", "schema": {
    "type": "object", "properties": {"reasons": {"type": "array", "items": {
        "type": "object", "properties": {"store_id": _STR, "reason": _STR},
        "required": ["store_id", "reason"], "additionalProperties": False}}},
    "required": ["reasons"], "additionalProperties": False}}


def _fallback_reason(tags: list[dict]) -> str:
    names = [t["name"] for t in tags[:3]]
    return f"Over-indexes on {', '.join(names)}." if names else "Not enough local taste data."


async def run_score(llm, tools, signature: list[dict]):
    res = await tools.score_stores(signature)
    scored = res["stores"]
    n = sum(s["fit"] is not None for s in scored)
    yield trace("score_stores", {"items": [i["name"] for i in signature]}, f"{n} of {len(scored)} stores scored")

    top, bottom = pick(scored)
    focus = top + bottom
    tastes = await asyncio.gather(*(tools.area_taste(s["id"]) for s in focus))
    evidence = {s["id"]: t["tags"] for s, t in zip(focus, tastes)}
    for s in focus:
        yield trace("area_taste", {"store": s["name"]}, _summarize(evidence[s["id"]]))

    reasons = {sid: _fallback_reason(tags) for sid, tags in evidence.items()}
    payload = [{"store_id": s["id"], "name": s["name"], "fit": s["fit"],
                "evidence": [t["name"] for t in evidence[s["id"]]]} for s in focus]
    try:
        resp = await create(llm, system=REASONS_SYSTEM, output_config={"format": REASONS_FORMAT},
                            messages=[{"role": "user", "content": json.dumps(
                                {"lto_signature": [i["name"] for i in signature], "stores": payload})}])
        for r in json.loads(_text(resp))["reasons"]:
            if r["store_id"] in reasons:
                reasons[r["store_id"]] = r["reason"]
    except (AgentError, json.JSONDecodeError, KeyError):
        pass  # keep the deterministic reasons

    stab = res["stability"]
    names = {i["id"]: i["name"] for i in signature}
    yield {"type": "result", "stores": scored, "top": [s["id"] for s in top], "bottom": [s["id"] for s in bottom],
           "reasons": reasons, "stability": {**stab, "weakest": names.get(stab["weakest"], stab["weakest"])} if stab else None}


# --- Store brief -----------------------------------------------------------------------------

BRIEF_SYSTEM = """You write a short localization brief for one coffee store and a new limited-time offer.
Return a one-sentence verdict (at most 25 words) explaining the fit, and 2-3 short menu cues.
Mention only taste facts from the provided local tags. Do not name any business, artist, or brand."""

BRIEF_FORMAT = {"type": "json_schema", "schema": {
    "type": "object", "properties": {"verdict": _STR, "menu_cues": {"type": "array", "items": _STR}},
    "required": ["verdict", "menu_cues"], "additionalProperties": False}}


def _label(fit: float | None) -> str:
    if fit is None:
        return "maybe"
    return "test" if fit >= 0.5 else "skip" if fit <= -0.5 else "maybe"


async def write_brief(llm, tools, store_id: str, signature: list[dict], fit: float | None) -> dict:
    store = tools.store(store_id)
    taste = await tools.area_taste(store_id)
    label = _label(fit)
    resp = await create(llm, system=BRIEF_SYSTEM, output_config={"format": BRIEF_FORMAT},
                        messages=[{"role": "user", "content": json.dumps({
                            "store": store["name"], "verdict_label": label, "fit_z_score": fit,
                            "lto_signature": [i["name"] for i in signature],
                            "local_tags": [t["name"] for t in taste["tags"]]})}])
    out = json.loads(_text(resp))
    return {"store_id": store_id, "fit": fit, "label": label, "verdict": out["verdict"],
            "why_tags": taste["tags"][:5], "partners": taste["places"][:3], "menu_cues": out["menu_cues"][:3]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_agent.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent.py backend/tests/test_agent.py
git commit -m "feat: Claude tool loop for taste signature, scoring run, and store brief"
```

---

### Task 6: FastAPI app (routes, SSE, rate limit, demos)

**Files:**
- Create: `backend/app/main.py`, `backend/tests/test_main.py`, `backend/data/demos/.gitkeep`

**Interfaces:**
- Consumes: `agent.build_signature`, `agent.run_score`, `agent.write_brief`, `Tools`, `Qloo`, `load_stores`.
- Produces HTTP API (used by the frontend in Tasks 7–9):
  - `GET /api/stores` → `[Store]`
  - `GET /api/demos` → `[{"slug","title","lto"}]`
  - `GET /api/demos/{slug}` → `{"slug","title","lto","signature","result","briefs","trace"}` (404 if the slug is unknown)
  - `POST /api/signature` `{"lto": str ≤500, "current": [SignatureItem]?, "instruction": str ≤300?}` → SSE stream of events
  - `POST /api/score` `{"signature": [SignatureItem] (1–8)}` → SSE stream of events
  - `POST /api/brief` `{"store_id", "signature", "fit"}` → Brief JSON (404 if the store is unknown)
  - SSE framing: each event is sent as `data: <json>\n\n`. Errors are sent in-stream as `{"type":"error","message":...}`.
  - 429 with `{"detail": "..."}` when the rate limit is exceeded.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_main.py`:
```python
import json

import pytest
from fastapi.testclient import TestClient

from app import agent, main
from app.agent import AgentError

STORES = [{"id": "a", "name": "A", "address": "x", "lat": 0.0, "lon": 0.0, "metro": "M"}]
SIG = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]


class FakeTools:
    stores = STORES

    def store(self, store_id):
        return {s["id"]: s for s in STORES}[store_id]


@pytest.fixture
def client(tmp_path, monkeypatch):
    main._hits.clear()
    main.app.state.tools = FakeTools()
    main.app.state.llm = object()
    monkeypatch.setattr(main, "DEMOS", tmp_path)
    (tmp_path / "matcha.json").write_text(json.dumps({"slug": "matcha", "title": "Matcha", "lto": "m"}))
    return TestClient(main.app)


def events(response):
    return [json.loads(line[6:]) for line in response.text.split("\n\n") if line.startswith("data: ")]


def test_stores(client):
    assert client.get("/api/stores").json() == STORES


def test_demos_list_and_get(client):
    assert client.get("/api/demos").json() == [{"slug": "matcha", "title": "Matcha", "lto": "m"}]
    assert client.get("/api/demos/matcha").json()["title"] == "Matcha"
    assert client.get("/api/demos/..%2Fsecrets").status_code == 404
    assert client.get("/api/demos/nope").status_code == 404


def test_signature_streams_events(client, monkeypatch):
    async def fake(llm, tools, lto, current=None, instruction=None):
        yield {"type": "trace", "tool": "find_tags", "args": {"query": lto}, "summary": "1 results"}
        yield {"type": "signature", "items": SIG, "dropped": 0}

    monkeypatch.setattr(agent, "build_signature", fake)
    r = client.post("/api/signature", json={"lto": "matcha"})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert [e["type"] for e in events(r)] == ["trace", "signature"]


def test_errors_are_sent_in_stream(client, monkeypatch):
    async def fake(llm, tools, signature):
        raise AgentError("the model declined this request")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "run_score", fake)
    r = client.post("/api/score", json={"signature": SIG})
    assert events(r) == [{"type": "error", "message": "the model declined this request"}]


def test_validation_rejects_bad_input(client):
    assert client.post("/api/signature", json={"lto": "x" * 501}).status_code == 422
    assert client.post("/api/score", json={"signature": []}).status_code == 422
    bad = [{**SIG[0], "weight": 3}]
    assert client.post("/api/score", json={"signature": bad}).status_code == 422


def test_rate_limit(client, monkeypatch):
    async def fake(llm, tools, signature):
        yield {"type": "result"}

    monkeypatch.setattr(agent, "run_score", fake)
    codes = [client.post("/api/score", json={"signature": SIG}).status_code for _ in range(7)]
    assert codes == [200] * 6 + [429]


def test_brief_unknown_store_404(client, monkeypatch):
    async def fake(llm, tools, store_id, signature, fit):
        tools.store(store_id)

    monkeypatch.setattr(agent, "write_brief", fake)
    assert client.post("/api/brief", json={"store_id": "zzz", "signature": SIG, "fit": None}).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_main.py -v`
Expected: FAIL with `ImportError: cannot import name 'main'`

- [ ] **Step 3: Implement `backend/app/main.py`**

```python
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent
from .qloo import Qloo
from .stores import load_stores
from .tools import Tools

ROOT = Path(__file__).resolve().parents[1]  # backend/
DATA = ROOT / "data"
DEMOS = DATA / "demos"
DIST = ROOT.parent / "frontend" / "dist"
LIMITS = {"live": 6, "brief": 30}  # per IP per hour

app = FastAPI(title="TasteTest")


class SignatureItem(BaseModel):
    id: str = Field(max_length=200)
    name: str = Field(max_length=200)
    kind: Literal["tag", "entity"]
    weight: float = Field(ge=0, le=1)
    substituted_from: str | None = Field(default=None, max_length=200)


class SignatureReq(BaseModel):
    lto: str = Field(min_length=1, max_length=500)
    current: list[SignatureItem] | None = Field(default=None, max_length=8)
    instruction: str | None = Field(default=None, max_length=300)


class ScoreReq(BaseModel):
    signature: list[SignatureItem] = Field(min_length=1, max_length=8)


class BriefReq(BaseModel):
    store_id: str = Field(max_length=100)
    signature: list[SignatureItem] = Field(min_length=1, max_length=8)
    fit: float | None = None


def deps(request: Request):
    s = request.app.state
    if not hasattr(s, "tools"):
        s.tools = Tools(Qloo(os.environ["QLOO_API_KEY"], DATA / "cache"), load_stores(DATA / "stores.csv"))
        s.llm = AsyncAnthropic()
    return s.llm, s.tools


# ponytail: in-memory per-IP limiter; resets on restart and assumes a single instance.
# X-Forwarded-For is set by Render's proxy; it is spoofable elsewhere.
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def check_rate(request: Request, bucket: str) -> None:
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()
    now, q = time.time(), _hits[(bucket, ip)]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= LIMITS[bucket]:
        raise HTTPException(429, "Live run limit reached for this hour. The preloaded examples still work.")
    q.append(now)


def sse(gen) -> StreamingResponse:
    async def body():
        try:
            async for ev in gen:
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:  # stream boundary: show the failure in the UI instead of a dead stream
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    return StreamingResponse(body(), media_type="text/event-stream")


def _items(items: list[SignatureItem] | None) -> list[dict] | None:
    return [i.model_dump() for i in items] if items is not None else None


@app.get("/api/stores")
def stores(request: Request):
    return deps(request)[1].stores


@app.get("/api/demos")
def demos():
    out = []
    for p in sorted(DEMOS.glob("*.json")):
        d = json.loads(p.read_text())
        out.append({"slug": d["slug"], "title": d["title"], "lto": d["lto"]})
    return out


@app.get("/api/demos/{slug}")
def demo(slug: str):
    if slug not in {p.stem for p in DEMOS.glob("*.json")}:
        raise HTTPException(404, "unknown demo")
    return json.loads((DEMOS / f"{slug}.json").read_text())


@app.post("/api/signature")
def signature(req: SignatureReq, request: Request):
    check_rate(request, "live")
    llm, tools = deps(request)
    return sse(agent.build_signature(llm, tools, req.lto, _items(req.current), req.instruction))


@app.post("/api/score")
def score(req: ScoreReq, request: Request):
    check_rate(request, "live")
    llm, tools = deps(request)
    return sse(agent.run_score(llm, tools, _items(req.signature)))


@app.post("/api/brief")
async def brief(req: BriefReq, request: Request):
    check_rate(request, "brief")
    llm, tools = deps(request)
    try:
        return await agent.write_brief(llm, tools, req.store_id, _items(req.signature), req.fit)
    except KeyError:
        raise HTTPException(404, "unknown store")
    except agent.AgentError as e:
        raise HTTPException(502, str(e))


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
```

Create an empty `backend/data/demos/.gitkeep`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest -v`
Expected: all tests pass (test_qloo 8, test_stores 1, test_scoring 12, test_tools 5, test_agent 10, test_main 7)

- [ ] **Step 5: Smoke-run the server**

Run: `cd backend && QLOO_API_KEY=dummy uvicorn app.main:app --port 8000` (in a separate terminal), then `curl -s localhost:8000/api/stores | head -c 200`
Expected: JSON with the 6 placeholder stores. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_main.py backend/data/demos/.gitkeep
git commit -m "feat: FastAPI routes with SSE streaming, rate limits, and demo runs"
```

---

### Task 7: Frontend shell + map

**Files:**
- Create: `frontend/` (Vite React scaffold), `frontend/vite.config.js`, `frontend/src/main.jsx`, `frontend/src/App.jsx`, `frontend/src/api.js`, `frontend/src/config.js`, `frontend/src/MapView.jsx`, `frontend/src/styles.css`
- Create (stubs, filled in Tasks 8–9): `frontend/src/InputCard.jsx`, `frontend/src/RankCard.jsx`, `frontend/src/TraceBar.jsx`, `frontend/src/StoreDrawer.jsx`

**Interfaces:**
- Consumes: the HTTP API from Task 6.
- Produces:
  - `api.js`: `streamPost(url, body, onEvent)`, `getJSON(url)`, `postJSON(url, body)`
  - `config.js`: `CHAIN`
  - `MapView({ stores, selected, metro, onSelect })` — stores may include `fit` and `confidence`
  - Component props used in Tasks 8–9:
    - `InputCard({ demos, lto, setLto, signature, setSignature, busy, onDemo, onReadTaste, onScore, storeCount })`
    - `RankCard({ result, busy, onSelect })`
    - `TraceBar({ trace, stability, metros, metro, onMetro })`
    - `StoreDrawer({ store, brief, onClose })`

- [ ] **Step 1: Scaffold and install**

```bash
npm create vite@latest frontend -- --template react
cd frontend && npm install && npm install maplibre-gl
rm -f src/App.css src/index.css src/assets/react.svg public/vite.svg
```
Expected: `frontend/package.json` exists and includes `react`, `react-dom`, `maplibre-gl`.

- [ ] **Step 2: Write config files**

`frontend/vite.config.js`:
```js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
```

`frontend/index.html` (replace the generated file):
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>TasteTest</title>
    <meta name="description" content="Find which coffee shops to test a new limited-time drink in, based on what each neighborhood actually likes." />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

`frontend/src/config.js`:
```js
// Set to the chain picked in Task 11. Used only in descriptive copy (no logo/colors).
export const CHAIN = "the chain";
```

`frontend/src/main.jsx`:
```jsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
```

- [ ] **Step 3: Write `frontend/src/api.js`**

```js
async function check(res) {
  if (res.ok) return res;
  const body = await res.json().catch(() => ({}));
  throw new Error(body.detail || `Request failed (${res.status})`);
}

export async function streamPost(url, body, onEvent) {
  const res = await check(await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (chunk.startsWith("data: ")) onEvent(JSON.parse(chunk.slice(6)));
    }
  }
}

export const getJSON = async (url) => (await check(await fetch(url))).json();

export const postJSON = async (url, body) => (await check(await fetch(url, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
}))).json();
```

- [ ] **Step 4: Write `frontend/src/MapView.jsx`**

```jsx
import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const STYLE = "https://tiles.openfreemap.org/styles/positron"; // free, no API key

function toGeoJSON(stores, selected) {
  return {
    type: "FeatureCollection",
    features: stores.map((s) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      properties: { id: s.id, fit: s.fit ?? null, confidence: s.confidence ?? "none", selected: s.id === selected },
    })),
  };
}

export default function MapView({ stores, selected, metro, onSelect }) {
  const container = useRef(null);
  const map = useRef(null);
  const onSelectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const m = new maplibregl.Map({ container: container.current, style: STYLE, center: [-98, 39], zoom: 3.5,
      attributionControl: { compact: true } });
    map.current = m;
    m.on("load", () => {
      m.addSource("stores", { type: "geojson", data: toGeoJSON([], null) });
      m.addLayer({
        id: "stores", type: "circle", source: "stores",
        paint: {
          "circle-radius": ["case", ["get", "selected"], 11, 7],
          "circle-color": ["case", ["==", ["get", "fit"], null], "#9b958a",
            ["interpolate", ["linear"], ["get", "fit"], -2, "#b4432f", 0, "#d9c9a0", 2, "#2f7d3a"]],
          "circle-opacity": ["match", ["get", "confidence"], "low", 0.4, 1],
          "circle-stroke-width": ["case", ["get", "selected"], 2.5, 1],
          "circle-stroke-color": "#1d1d1f",
        },
      });
      m.on("click", "stores", (e) => onSelectRef.current(e.features[0].properties.id));
      m.on("mouseenter", "stores", () => { m.getCanvas().style.cursor = "pointer"; });
      m.on("mouseleave", "stores", () => { m.getCanvas().style.cursor = ""; });
      setReady(true);
    });
    return () => m.remove();
  }, []);

  useEffect(() => {
    if (ready) map.current.getSource("stores").setData(toGeoJSON(stores, selected));
  }, [ready, stores, selected]);

  useEffect(() => {
    const inView = stores.filter((s) => !metro || s.metro === metro);
    if (!ready || inView.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    inView.forEach((s) => bounds.extend([s.lon, s.lat]));
    const padding = window.innerWidth > 800 ? { top: 120, bottom: 140, left: 380, right: 420 } : 40;
    map.current.fitBounds(bounds, { padding, maxZoom: 13, duration: 800 });
  }, [ready, metro, stores.length]);

  return <div ref={container} className="map" role="region" aria-label="Map of stores colored by fit" />;
}
```

- [ ] **Step 5: Write `frontend/src/App.jsx` and stub components**

`frontend/src/App.jsx`:
```jsx
import { useEffect, useMemo, useState } from "react";
import { getJSON, postJSON, streamPost } from "./api";
import MapView from "./MapView";
import InputCard from "./InputCard";
import RankCard from "./RankCard";
import TraceBar from "./TraceBar";
import StoreDrawer from "./StoreDrawer";

export default function App() {
  const [stores, setStores] = useState([]);
  const [demos, setDemos] = useState([]);
  const [lto, setLto] = useState("");
  const [signature, setSignature] = useState([]);
  const [result, setResult] = useState(null);
  const [briefs, setBriefs] = useState({});
  const [trace, setTrace] = useState([]);
  const [selected, setSelected] = useState(null);
  const [metro, setMetro] = useState(null);
  const [busy, setBusy] = useState(null); // "signature" | "score" | null
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([getJSON("/api/stores"), getJSON("/api/demos")])
      .then(([s, d]) => { setStores(s); setDemos(d); if (d.length) loadDemo(d[0].slug); })
      .catch((e) => setError(e.message));
  }, []);

  async function loadDemo(slug) {
    try {
      const d = await getJSON(`/api/demos/${slug}`);
      setLto(d.lto); setSignature(d.signature); setResult(d.result);
      setBriefs(d.briefs || {}); setTrace(d.trace || []); setSelected(null); setError(null);
    } catch (e) { setError(e.message); }
  }

  function onEvent(ev) {
    if (ev.type === "trace") setTrace((t) => [...t, ev]);
    else if (ev.type === "signature") setSignature(ev.items);
    else if (ev.type === "result") setResult(ev);
    else if (ev.type === "error") setError(ev.message);
  }

  async function run(kind, url, body) {
    setBusy(kind); setError(null);
    if (kind === "signature") setTrace([]);
    if (kind === "score") { setResult(null); setBriefs({}); setSelected(null); }
    try { await streamPost(url, body, onEvent); } catch (e) { setError(e.message); } finally { setBusy(null); }
  }

  const readTaste = (instruction) =>
    run("signature", "/api/signature", instruction ? { lto, current: signature, instruction } : { lto });
  const scoreStores = () => run("score", "/api/score", { signature });

  const shown = result ? result.stores : stores;
  const selectedStore = shown.find((s) => s.id === selected);
  const metros = useMemo(() => [...new Set(stores.map((s) => s.metro))].sort(), [stores]);

  async function openStore(id) {
    setSelected(id);
    if (briefs[id] || signature.length === 0) return;
    const fit = result?.stores.find((s) => s.id === id)?.fit ?? null;
    try {
      const b = await postJSON("/api/brief", { store_id: id, signature, fit });
      setBriefs((m) => ({ ...m, [id]: b }));
    } catch (e) { setError(e.message); }
  }

  return (
    <div className="app">
      <MapView stores={shown} selected={selected} metro={metro} onSelect={openStore} />
      <InputCard demos={demos} lto={lto} setLto={setLto} signature={signature} setSignature={setSignature}
        busy={busy} onDemo={loadDemo} onReadTaste={readTaste} onScore={scoreStores} storeCount={stores.length} />
      {selectedStore
        ? <StoreDrawer store={selectedStore} brief={briefs[selected]} onClose={() => setSelected(null)} />
        : <RankCard result={result} busy={busy === "score"} onSelect={openStore} />}
      <TraceBar trace={trace} stability={result?.stability} metros={metros} metro={metro} onMetro={setMetro} />
      {error && <div className="toast" role="alert">{error} <button onClick={() => setError(null)} aria-label="Dismiss">×</button></div>}
    </div>
  );
}
```

Stubs, so the app renders now (replaced in Tasks 8–9):

`frontend/src/InputCard.jsx`: `export default function InputCard() { return <section className="card input-card">Input</section>; }`
`frontend/src/RankCard.jsx`: `export default function RankCard() { return <section className="card rank-card">Ranking</section>; }`
`frontend/src/TraceBar.jsx`: `export default function TraceBar() { return <footer className="card trace-bar">Trace</footer>; }`
`frontend/src/StoreDrawer.jsx`: `export default function StoreDrawer() { return <aside className="card drawer">Store</aside>; }`

- [ ] **Step 6: Write `frontend/src/styles.css`**

```css
:root {
  --bg: #e9e5dc; --card: #fffdf8; --line: #ddd6c8; --ink: #1d1d1f; --muted: #8a857c;
  --green: #2f7d3a; --green-dark: #2f5d3a; --red: #b4432f;
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; color: var(--ink);
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); }
button { font: inherit; cursor: pointer; }
button:disabled { cursor: default; opacity: 0.5; }
.app { position: fixed; inset: 0; }
.map { position: absolute; inset: 0; }
.card { position: absolute; background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  box-shadow: 0 4px 18px rgba(0,0,0,.12); padding: 14px; }
.input-card { top: 14px; left: 14px; width: 340px; max-height: calc(100vh - 150px); overflow: auto; }
.rank-card, .drawer { top: 14px; right: 14px; width: 380px; max-height: calc(100vh - 150px); overflow: auto; }
.trace-bar { left: 14px; right: 14px; bottom: 14px; padding: 8px 14px; font-size: 12px; }
h1 { margin: 0; font-size: 18px; } h2 { margin: 0; font-size: 16px; }
.sub, .muted, .src, .fine, .why { color: var(--muted); }
.sub { margin: 2px 0 10px; } .src { font-size: 11px; } .fine { margin: 6px 0 0; font-size: 11px; }
.label { margin: 12px 0 6px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
textarea, .input { width: 100%; border: 1px solid var(--line); border-radius: 8px; padding: 8px; font: inherit; background: #fff; }
textarea { height: 72px; resize: vertical; }
.btn { display: block; width: 100%; margin-top: 10px; padding: 9px; border: 0; border-radius: 8px; background: var(--green-dark); color: #fff; font-weight: 600; }
.btn.secondary { background: #fff; color: var(--green-dark); border: 1px solid var(--green-dark); }
.chips { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.chip { display: inline-flex; align-items: center; gap: 4px; background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 2px 4px 2px 10px; font-size: 12px; }
.chip button { border: 0; background: none; color: var(--muted); padding: 0 4px; }
.chip s { color: var(--muted); }
.pill { border: 1px solid var(--line); background: #fff; border-radius: 14px; padding: 3px 10px; font-size: 12px; margin: 0 4px 4px 0; }
.pill.on { background: var(--green-dark); color: #fff; border-color: var(--green-dark); }
ul { list-style: none; margin: 0; padding: 0; }
.row { display: block; width: 100%; text-align: left; border: 0; border-bottom: 1px solid #ece6da; background: none; padding: 7px 0; }
.row-main { display: flex; justify-content: space-between; }
.why { display: block; font-size: 12px; }
.up { color: var(--green); font-weight: 700; } .dn { color: var(--red); font-weight: 700; }
.trace-row { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; }
.metros { margin-left: auto; }
.link { border: 0; background: none; padding: 0; color: var(--ink); }
.trace { max-height: 160px; overflow: auto; margin: 8px 0 0; padding-left: 18px; }
.drawer-head { display: flex; gap: 10px; align-items: flex-start; justify-content: space-between; }
.fit { font-size: 20px; }
.close { border: 0; background: none; font-size: 20px; line-height: 1; color: var(--muted); }
.verdict { margin: 10px 0; }
.meter { position: relative; height: 6px; border-radius: 3px; background: #eee; margin: 6px 0 2px; }
.meter i { position: absolute; left: 50%; top: -3px; width: 2px; height: 12px; background: #999; }
.meter b { position: absolute; height: 6px; background: var(--green); border-radius: 3px; }
.sec { margin-top: 12px; padding-top: 10px; border-top: 1px solid #ece6da; }
.ent { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.ent img, .ent .thumb { width: 26px; height: 26px; border-radius: 4px; object-fit: cover; background: #cfc8b8; flex: none; }
.toast { position: absolute; left: 50%; top: 14px; transform: translateX(-50%); background: var(--red); color: #fff; padding: 8px 12px; border-radius: 8px; }
.toast button { border: 0; background: none; color: #fff; }
@media (max-width: 800px) {
  .input-card, .rank-card, .drawer { position: absolute; left: 8px; right: 8px; width: auto; }
  .input-card { top: 8px; max-height: 40vh; }
  .rank-card, .drawer { top: auto; bottom: 120px; max-height: 38vh; }
  .trace-bar { left: 8px; right: 8px; bottom: 8px; }
}
```

- [ ] **Step 7: Verify in the browser**

Run the backend (`cd backend && QLOO_API_KEY=dummy uvicorn app.main:app --port 8000`) and the frontend (`cd frontend && npm run dev`). Open http://localhost:5173.
Expected: a full-screen map with 6 grey dots across NYC and LA, the four stub cards, and no console errors. (`/api/demos` returns `[]` until Task 12.)

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat: frontend shell with MapLibre store map and SSE client"
```

---

### Task 8: Input card, ranking card, trace bar

**Files:**
- Modify: `frontend/src/InputCard.jsx`, `frontend/src/RankCard.jsx`, `frontend/src/TraceBar.jsx` (replace the stubs)

**Interfaces:**
- Consumes: props listed in Task 7, `CHAIN` from `config.js`, and the `result` event shape.

- [ ] **Step 1: Write `frontend/src/InputCard.jsx`**

```jsx
import { useState } from "react";

export default function InputCard({ demos, lto, setLto, signature, setSignature, busy, onDemo, onReadTaste, onScore, storeCount }) {
  const [instruction, setInstruction] = useState("");

  function refine(e) {
    e.preventDefault();
    if (!instruction.trim()) return;
    onReadTaste(instruction.trim());
    setInstruction("");
  }

  return (
    <section className="card input-card" aria-label="New limited-time offer">
      <h1>TasteTest</h1>
      <p className="sub">Where should your next limited-time drink launch first?</p>
      {demos.length > 0 && (
        <div>{demos.map((d) => <button key={d.slug} className="pill" onClick={() => onDemo(d.slug)}>{d.title}</button>)}</div>
      )}
      <label className="label" htmlFor="lto">New LTO</label>
      <textarea id="lto" maxLength={500} value={lto} onChange={(e) => setLto(e.target.value)}
        placeholder="e.g. matcha-yuzu cold brew, bright and citrusy, for a younger crowd" />
      <button className="btn secondary" disabled={!lto.trim() || !!busy} onClick={() => onReadTaste()}>
        {busy === "signature" ? "Reading the taste…" : "Read the taste"}
      </button>

      {signature.length > 0 && (
        <>
          <div className="label">Taste signature</div>
          <div className="chips">
            {signature.map((i) => (
              <span key={i.id} className="chip" title={`weight ${i.weight}`}>
                {i.substituted_from && <><s>{i.substituted_from}</s>&nbsp;→</>}
                {i.name}
                <button aria-label={`Remove ${i.name}`} disabled={!!busy}
                  onClick={() => setSignature(signature.filter((x) => x.id !== i.id))}>×</button>
              </span>
            ))}
          </div>
          <form onSubmit={refine}>
            <input className="input" aria-label="Adjust the signature" maxLength={300} value={instruction}
              onChange={(e) => setInstruction(e.target.value)} disabled={!!busy}
              placeholder="Adjust: “aim at an older crowd”" />
          </form>
          <button className="btn" disabled={!!busy || signature.length === 0} onClick={onScore}>
            {busy === "score" ? "Scoring…" : `Score ${storeCount} stores`}
          </button>
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Write `frontend/src/RankCard.jsx`**

```jsx
function fmt(fit) {
  return `${fit > 0 ? "+" : ""}${fit.toFixed(1)}`;
}

export default function RankCard({ result, busy, onSelect }) {
  if (!result) {
    return (
      <section className="card rank-card">
        <p className="muted">{busy ? "Scoring stores against local taste…" : "Read the taste, then score stores to see where to test."}</p>
      </section>
    );
  }
  const byId = Object.fromEntries(result.stores.map((s) => [s.id, s]));
  const Row = ({ id }) => {
    const s = byId[id];
    return (
      <li>
        <button className="row" onClick={() => onSelect(id)}>
          <span className="row-main"><span>{s.name}</span><span className={s.fit >= 0 ? "up" : "dn"}>{fmt(s.fit)}</span></span>
          {result.reasons?.[id] && <span className="why">{result.reasons[id]}</span>}
          {s.confidence === "low" && <span className="why">Thin data here. Treat with caution.</span>}
        </button>
      </li>
    );
  };
  return (
    <section className="card rank-card" aria-label="Store ranking">
      <div className="label" style={{ marginTop: 0 }}>Test here</div>
      <ul>{result.top.map((id) => <Row key={id} id={id} />)}</ul>
      {result.bottom.length > 0 && (
        <>
          <div className="label">Skip</div>
          <ul>{result.bottom.map((id) => <Row key={id} id={id} />)}</ul>
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Write `frontend/src/TraceBar.jsx`**

```jsx
import { useState } from "react";
import { CHAIN } from "./config";

export default function TraceBar({ trace, stability, metros, metro, onMetro }) {
  const [open, setOpen] = useState(false);
  return (
    <footer className="card trace-bar">
      <div className="trace-row">
        <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "▾" : "▸"} Agent trace · {trace.length} calls
        </button>
        {stability && (
          <span title="Leave-one-out Spearman correlation between the full ranking and the ranking with one concept removed">
            {stability.rho >= 0.7 ? "✓" : "⚠"} Ranking holds when any single concept is dropped: ρ ≥ {stability.rho.toFixed(2)} · most sensitive to “{stability.weakest}”
          </span>
        )}
        <span className="metros">
          {[null, ...metros].map((m) => (
            <button key={m ?? "all"} className={`pill ${m === metro ? "on" : ""}`} onClick={() => onMetro(m)}>{m ?? "All"}</button>
          ))}
        </span>
      </div>
      {open && (
        <ol className="trace">
          {trace.map((t, i) => <li key={i}><code>{t.tool}</code> {JSON.stringify(t.args)} → {t.summary}</li>)}
        </ol>
      )}
      <p className="fine">Fit is relative to each city. Prioritizes which stores to test in. Not a sales forecast. Not affiliated with {CHAIN}.</p>
    </footer>
  );
}
```

- [ ] **Step 4: Verify in the browser**

Temporarily add a demo file so there is data to render. Create `backend/data/demos/sample.json`:
```json
{"slug": "sample", "title": "Sample", "lto": "matcha-yuzu cold brew",
 "signature": [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": null},
               {"id": "T2", "name": "citrus", "kind": "tag", "weight": 0.7, "substituted_from": "yuzu"}],
 "result": {"type": "result",
   "stores": [
     {"id": "nyc-williamsburg", "name": "Williamsburg", "address": "", "lat": 40.7193, "lon": -73.9590, "metro": "New York", "fit": 1.8, "confidence": "high"},
     {"id": "la-silver-lake", "name": "Silver Lake", "address": "", "lat": 34.0912, "lon": -118.2790, "metro": "Los Angeles", "fit": 1.1, "confidence": "high"},
     {"id": "nyc-west-village", "name": "West Village", "address": "", "lat": 40.7335, "lon": -74.0040, "metro": "New York", "fit": 0.3, "confidence": "low"},
     {"id": "la-arts-district", "name": "Arts District", "address": "", "lat": 34.0470, "lon": -118.2350, "metro": "Los Angeles", "fit": -0.2, "confidence": "high"},
     {"id": "la-century-city", "name": "Century City", "address": "", "lat": 34.0590, "lon": -118.4170, "metro": "Los Angeles", "fit": -1.2, "confidence": "high"},
     {"id": "nyc-midtown-east", "name": "Midtown East", "address": "", "lat": 40.7572, "lon": -73.9693, "metro": "New York", "fit": -1.6, "confidence": "high"}],
   "top": ["nyc-williamsburg", "la-silver-lake", "nyc-west-village", "la-arts-district", "la-century-city"],
   "bottom": ["nyc-midtown-east"],
   "reasons": {"nyc-williamsburg": "Over-indexes on japanese cafe and matcha.", "nyc-midtown-east": "Leans business-lunch; little tea culture."},
   "stability": {"rho": 0.86, "weakest": "Matcha"}},
 "briefs": {}, "trace": [{"type": "trace", "tool": "find_tags", "args": {"query": "matcha"}, "summary": "3 results: matcha"}]}
```
Reload http://localhost:5173.
Expected:
- The sample loads automatically.
- The map shows dots colored green to red, and West Village appears faded.
- The ranking card lists the 5 "Test here" stores and 1 "Skip" store with reasons.
- The chips include "~~yuzu~~ → citrus", and clicking × removes a chip.
- The trace bar shows the stability line (✓ ρ ≥ 0.86 · most sensitive to “Matcha”) and expands to show 1 call. The metro pills fly the map to each city.
- At 375px width (use the browser pane's resize), the cards stack and there is no horizontal scroll.

Delete `backend/data/demos/sample.json` after checking. Real demos come in Task 12.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/InputCard.jsx frontend/src/RankCard.jsx frontend/src/TraceBar.jsx
git commit -m "feat: input card with signature chips, ranking card, trace bar"
```

---

### Task 9: Store drawer

**Files:**
- Modify: `frontend/src/StoreDrawer.jsx` (replace the stub)

**Interfaces:**
- Consumes: `StoreDrawer({ store, brief, onClose })`. `store` is a ScoredStore or plain Store; `brief` is a Brief or `undefined` while loading.

- [ ] **Step 1: Write `frontend/src/StoreDrawer.jsx`**

```jsx
const LABEL = { test: "✅ Test here.", maybe: "➖ Maybe.", skip: "⛔ Skip." };

function Meter({ fit, confidence }) {
  const pct = Math.max(-1, Math.min(1, fit / 2.5)) * 50;
  const bar = pct >= 0 ? { left: "50%", width: `${pct}%` } : { left: `${50 + pct}%`, width: `${-pct}%`, background: "var(--red)" };
  return (
    <div>
      <div className="meter"><i /><b style={bar} /></div>
      <div className="src">fit vs. chain average (relative to each city) · confidence: {confidence}</div>
    </div>
  );
}

function Entity({ e }) {
  return (
    <div className="ent">
      {e.image ? <img src={e.image} alt="" /> : <span className="thumb" />}
      <span>{e.name}</span>
      {e.affinity != null && <span className="src">· affinity {e.affinity.toFixed(2)}</span>}
    </div>
  );
}

function Section({ title, children }) {
  return <div className="sec"><div className="label" style={{ marginTop: 0 }}>{title}</div>{children}</div>;
}

export default function StoreDrawer({ store, brief, onClose }) {
  return (
    <aside className="card drawer" aria-label={`${store.name} brief`}>
      <header className="drawer-head">
        <div><h2>{store.name}</h2><div className="src">{store.address}</div></div>
        {store.fit != null && <span className={`fit ${store.fit >= 0 ? "up" : "dn"}`}>{store.fit > 0 ? "+" : ""}{store.fit.toFixed(1)}</span>}
        <button className="close" aria-label="Close" onClick={onClose}>×</button>
      </header>
      {!brief ? <p className="muted">Building this store's brief…</p> : (
        <>
          <p className="verdict"><b>{LABEL[brief.label]}</b> {brief.verdict}</p>
          {store.fit != null && <Meter fit={store.fit} confidence={store.confidence} />}
          <Section title="Why">
            <div className="chips">{brief.why_tags.map((t) => <span key={t.id} className="chip" style={{ paddingRight: 10 }}>{t.name}</span>)}</div>
            <div className="src">Qloo taste analysis · 1.2 km radius</div>
          </Section>
          {brief.partners.length > 0 && <Section title="Local collab partners">{brief.partners.map((p) => <Entity key={p.id} e={p} />)}</Section>}
          <Section title="Menu cues"><ul>{brief.menu_cues.map((c, i) => <li key={i}>• {c}</li>)}</ul></Section>
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 2: Verify in the browser**

Recreate the Task 8 `sample.json` and add a brief for Williamsburg under `"briefs"`:
```json
"briefs": {"nyc-williamsburg": {"store_id": "nyc-williamsburg", "fit": 1.8, "label": "test",
  "verdict": "The neighborhood leans hard into Japanese cafe culture.",
  "why_tags": [{"id": "T9", "name": "japanese cafe", "affinity": 0.9}, {"id": "T1", "name": "matcha", "affinity": 0.8}],
  "partners": [{"id": "P1", "name": "Sample Tea Shop", "affinity": 0.81, "image": null}],
  "menu_cues": ["Lead with the matcha base", "Pair with a citrus pastry"]}}
```
Click the Williamsburg dot.
Expected:
- The drawer replaces the ranking card and shows the verdict line on top, then the meter, Why, Local collab partners and Menu cues.
- × returns to the ranking.
- Clicking a store with no brief shows "Building this store's brief…" and then an error toast (the dummy key can't reach Qloo). That's expected without keys.

Delete `sample.json` afterwards.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/StoreDrawer.jsx
git commit -m "feat: store drawer with verdict-first single-scroll brief"
```

---

### Task 10: Capture live Qloo fixtures (needs Qloo key)

The response formats and constants were confirmed by a live probe on 2026-10-06, and Tasks 1 and 3 already reflect what it found. This task saves real responses so the parsers stay pinned to them.

**Files:**
- Create: `backend/scripts/probe_qloo.py`, `backend/tests/fixtures/*.json` (generated), `backend/tests/test_fixtures.py`

**Interfaces:**
- Consumes: `Qloo` from Task 1. The key is read from the environment. Locally, load it with `set -a; . ../.env; set +a` from `backend/`.

- [ ] **Step 1: Write `backend/scripts/probe_qloo.py`**

```python
"""Capture one real response for every Qloo call TasteTest makes, saved as test fixtures.

Usage (from backend/): set -a; . ../.env; set +a; python scripts/probe_qloo.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import qloo as Q  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
LAT, LON = 40.7335, -74.0040  # West Village, NYC
CALLS = {
    "tag_search": ("/v2/tags", {"filter.query": "matcha", "take": 10}, Q.parse_tag_search),
    "search": ("/search", {"query": "matcha", "types": "urn:entity:place", "take": 5}, Q.parse_search),
    "heatmap": ("/v2/insights", {"filter.type": "urn:heatmap", "filter.location.query": "NYC",
                                 "signal.interests.tags": "urn:tag:specialty_dish:place:matcha"}, Q.parse_heatmap),
    "area_tags": ("/v2/insights", {"filter.type": "urn:tag", "signal.location": Q.point(LAT, LON),
                                   "signal.location.radius": 1200, "take": 10}, Q.parse_area_tags),
    "area_place": ("/v2/insights", {"filter.type": "urn:entity:place", "filter.location": Q.point(LAT, LON),
                                    "filter.location.radius": 1200, "take": 5}, Q.parse_entities),
}


async def main():
    FIX.mkdir(parents=True, exist_ok=True)
    client = Q.Qloo(os.environ["QLOO_API_KEY"], FIX.parent / ".probe-cache")
    for name, (path, params, parser) in CALLS.items():
        raw = await client.get(path, params)
        (FIX / f"{name}.json").write_text(json.dumps(raw, indent=1))
        parsed = parser(raw)
        print(f"[{name}] {len(parsed)} parsed; first: {parsed[:1]}")


if __name__ == "__main__":
    asyncio.run(main())
```

Add `backend/tests/.probe-cache/` to `.gitignore`.

- [ ] **Step 2: Run the probe**

Run: `cd backend && set -a && . ../.env && set +a && python scripts/probe_qloo.py`
Expected: 5 lines, each `N parsed` with N > 0 (the heatmap has ~44 cells). If a parser raises, the API has changed since 2026-10-06. Open the fixture, fix only the matching `parse_*` in `app/qloo.py`, and update `test_qloo.py::test_parsers` to the new shape.

- [ ] **Step 3: Write `backend/tests/test_fixtures.py`**

```python
"""Parsers must keep working on real Qloo responses captured by scripts/probe_qloo.py."""
import json
from pathlib import Path

import pytest

from app import qloo as Q

FIX = Path(__file__).parent / "fixtures"
CASES = [("tag_search", Q.parse_tag_search), ("search", Q.parse_search), ("heatmap", Q.parse_heatmap),
         ("area_tags", Q.parse_area_tags), ("area_place", Q.parse_entities)]


@pytest.mark.parametrize("name,parser", CASES)
def test_parser_on_real_response(name, parser):
    f = FIX / f"{name}.json"
    if not f.exists():
        pytest.skip(f"run scripts/probe_qloo.py to capture {name}")
    parsed = parser(json.loads(f.read_text()))
    assert parsed, f"{name} parsed to an empty list"
    assert all(p.get("id") or "affinity" in p for p in parsed)
```

- [ ] **Step 4: Run the full suite**

Run: `cd backend && pytest -v`
Expected: all pass, and the 5 fixture tests pass rather than skip.

- [ ] **Step 5: Commit**

```bash
git add .gitignore backend/scripts/probe_qloo.py backend/tests/fixtures backend/tests/test_fixtures.py
git commit -m "test: pin Qloo parsers to live response fixtures"
```

---

### Task 11: Philz store list and per-metro coverage (needs Qloo key)

**Files:**
- Create: `backend/scripts/coverage_check.py`, `backend/data/candidates/raw/philz.csv` (hand-collected), `backend/data/candidates/philz.csv` (geocoded)
- Modify: `backend/data/stores.csv` (replaced with covered Philz stores), `frontend/src/config.js`

**Interfaces:**
- Consumes: `Qloo.heatmap`, `scoring.nearest_cell`, `scoring.MAX_CELL_KM`, `stores.load_stores`, `scripts/geocode.py`.

- [ ] **Step 1: Collect Philz store addresses**

From Philz's public store locator, copy every US store into `backend/data/candidates/raw/philz.csv`:
```
id,name,address,metro
philz-sf-mission,24th St (Mission),3101 24th St San Francisco CA,San Francisco
...
```
Ids are `philz-<metro>-<neighborhood>` in lowercase with hyphens. `metro` is the city name sent to Qloo as `filter.location.query` (e.g. "San Francisco", "Oakland", "Palo Alto", "Los Angeles"), so use the store's own city.

- [ ] **Step 2: Geocode**

Run: `cd backend && python scripts/geocode.py data/candidates/raw/philz.csv data/candidates/philz.csv`
Expected: `wrote N/N stores`. For any SKIPPED row, fix the address and re-run.

- [ ] **Step 3: Write `backend/scripts/coverage_check.py`**

```python
"""Which Philz metros have enough Qloo heatmap data to include in the demo?

Usage (from backend/): python scripts/coverage_check.py data/candidates/philz.csv [--write data/stores.csv]
Per metro and reference tag: heatmap cell count, and how many of the metro's stores have a cell within MAX_CELL_KM.
A metro is kept only if every reference tag has at least MIN_CELLS cells.
"""
import asyncio
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.qloo import Qloo, QlooError  # noqa: E402
from app.scoring import MAX_CELL_KM, nearest_cell  # noqa: E402
from app.stores import load_stores  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"
REFERENCE_TAGS = ["urn:tag:specialty_dish:place:matcha", "urn:tag:specialty_dish:place:coffee"]
MIN_CELLS = 10


async def main(src: str, write_to: str | None) -> None:
    q = Qloo(os.environ["QLOO_API_KEY"], DATA / "cache")
    stores = load_stores(Path(src))
    keep = []
    header = "".join(f"{t.rsplit(':', 1)[-1] + ' cells':>14}{'near':>6}" for t in REFERENCE_TAGS)
    print(f"{'metro':<20}{'stores':>7}{header}")
    for metro in sorted({s["metro"] for s in stores}):
        ms = [s for s in stores if s["metro"] == metro]
        row, ok = f"{metro:<20}{len(ms):>7}", True
        for tag in REFERENCE_TAGS:  # sequential on purpose: the API rate-limits bursts
            try:
                cells = await q.heatmap({"id": tag, "kind": "tag"}, metro)
            except QlooError:
                cells = []
            near = sum(nearest_cell(cells, s["lat"], s["lon"], MAX_CELL_KM) is not None for s in ms)
            row += f"{len(cells):>14}{near:>6}"
            ok = ok and len(cells) >= MIN_CELLS
        print(row + ("  KEEP" if ok else "  drop"))
        keep += ms if ok else []
    if write_to:
        with open(write_to, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "name", "address", "lat", "lon", "metro"])
            w.writeheader()
            w.writerows(keep)
        print(f"wrote {len(keep)} stores to {write_to}")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(main(args[0], args[args.index("--write") + 1] if "--write" in args else None))
```

- [ ] **Step 4: Run it**

Run: `cd backend && set -a && . ../.env && set +a && python scripts/coverage_check.py data/candidates/philz.csv`
Expected: one row per metro. San Francisco should show well over 10 cells (156 for matcha in the probe).

If a Bay Area suburb is dropped for low coverage, try its stores with `metro` set to the nearest big city that Qloo covers (e.g. "San Francisco" or "San Jose"), then re-geocode and re-run. Larger query areas return more cells. Accept the drop if it's still under 10.

- [ ] **Step 5: Write the demo store list**

Run: `cd backend && python scripts/coverage_check.py data/candidates/philz.csv --write data/stores.csv`
Then set `CHAIN = "Philz Coffee"` in `frontend/src/config.js`.

Run: `cd backend && python -c "from app.stores import load_stores; s=load_stores('data/stores.csv'); print(len(s), sorted({x['metro'] for x in s}))"`
Expected: 15+ stores across at least 2 metros. If only one metro survives, that's acceptable: the map still compares neighborhoods. Note it in the README.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/coverage_check.py backend/data/candidates backend/data/stores.csv frontend/src/config.js
git commit -m "data: Philz stores in metros with Qloo heatmap coverage"
```

---

### Task 12: Precompute demo runs (needs both keys)

**Files:**
- Create: `backend/scripts/precompute_demos.py`, `backend/data/demos/{matcha-yuzu,maple-oat,smoky-tonic}.json` (generated)

**Interfaces:**
- Consumes: `agent.build_signature`, `agent.run_score`, `agent.write_brief`, `Tools`, `Qloo`, `load_stores`.
- Produces: demo JSON files in the `GET /api/demos/{slug}` shape from Task 6.

- [ ] **Step 1: Write `backend/scripts/precompute_demos.py`**

```python
"""Run the full pipeline for the preloaded examples and save results, so judges get instant, outage-proof demos.

Usage: QLOO_API_KEY=... ANTHROPIC_API_KEY=... python scripts/precompute_demos.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anthropic import AsyncAnthropic  # noqa: E402

from app import agent  # noqa: E402
from app.qloo import Qloo  # noqa: E402
from app.stores import load_stores  # noqa: E402
from app.tools import Tools  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"
DEMOS = [
    ("matcha-yuzu", "Matcha-yuzu cold brew", "Matcha-yuzu cold brew: bright, citrusy, aimed at a younger crowd"),
    ("maple-oat", "Brown-butter maple oat latte", "Brown-butter maple oat latte: cozy, nostalgic, fall comfort"),
    ("smoky-tonic", "Smoky cold brew tonic", "Smoky cold brew tonic: bold and adventurous, for the after-work crowd"),
]


async def run_one(llm, tools, slug, title, lto):
    trace, signature, result = [], None, None
    async for ev in agent.build_signature(llm, tools, lto):
        if ev["type"] == "trace":
            trace.append(ev)
        else:
            signature = ev["items"]
    async for ev in agent.run_score(llm, tools, signature):
        if ev["type"] == "trace":
            trace.append(ev)
        else:
            result = ev
    fits = {s["id"]: s["fit"] for s in result["stores"]}
    ids = result["top"] + result["bottom"]
    briefs = await asyncio.gather(*(agent.write_brief(llm, tools, i, signature, fits[i]) for i in ids))
    out = {"slug": slug, "title": title, "lto": lto, "signature": signature, "result": result,
           "briefs": dict(zip(ids, briefs)), "trace": trace}
    (DATA / "demos" / f"{slug}.json").write_text(json.dumps(out, indent=1))
    print(f"{slug}: {len(signature)} concepts, top={result['top'][:3]}, stability={result['stability']}")


async def main():
    tools = Tools(Qloo(os.environ["QLOO_API_KEY"], DATA / "cache"), load_stores(DATA / "stores.csv"))
    llm = AsyncAnthropic()
    for d in DEMOS:
        await run_one(llm, tools, *d)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it**

Run: `cd backend && QLOO_API_KEY=<key> ANTHROPIC_API_KEY=<key> python scripts/precompute_demos.py`
Expected: 3 lines, each with 3–8 concepts, a top-3 list and a stability dict.

- [ ] **Step 3: Sanity-check the results by reading them**

For each demo, open the JSON and check:
- The top and bottom stores make intuitive sense for the drink. Matcha should not top a business district.
- Every reason cites tags that appear in Qloo evidence.
- Every brief's partners are real nearby Qloo places.
- `stability.rho` is at least ~0.7. If it's lower, the ranking hangs on one concept: reword the LTO so the signature has 3+ solid dish/drink concepts, then re-run.

If a ranking looks wrong, inspect the signature first. Edit the demo LTO wording and re-run. Do not hand-edit results.

- [ ] **Step 4: Verify end to end in the browser**

Run the backend with real keys and `npm run dev`.
Expected:
- The first demo loads instantly.
- Clicking a top store opens its precomputed brief with no network call (check the network panel).
- Typing a new LTO → **Read the taste** streams trace lines and shows chips.
- **Score stores** colors the map, and clicking a non-demo store fetches a live brief.
- "Adjust: older crowd" re-runs the signature.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/precompute_demos.py backend/data/demos/*.json
git commit -m "data: precomputed demo runs for 3 LTOs"
```

---

### Task 13: Deploy, license, README, submission text (needs both keys)

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `render.yaml`, `LICENSE`, `README.md`

- [ ] **Step 1: Write `Dockerfile` and `.dockerignore`**

`Dockerfile`:
```dockerfile
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

`.dockerignore`:
```
**/node_modules
**/.venv
**/__pycache__
frontend/dist
backend/data/cache
backend/tests/.probe-cache
.superpowers
.git
```

- [ ] **Step 2: Test the image locally**

```bash
docker build -t tastetest .
docker run --rm -p 8000:8000 -e QLOO_API_KEY=<key> -e ANTHROPIC_API_KEY=<key> tastetest
```
Open http://localhost:8000.
Expected: the full app, served from one origin, with the first demo loaded.

- [ ] **Step 3: Write `render.yaml`**

```yaml
services:
  - type: web
    name: tastetest
    runtime: docker
    plan: starter # free plan sleeps; a ~50s cold start could hit a judge's first click
    healthCheckPath: /api/demos
    envVars:
      - key: QLOO_API_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
```

- [ ] **Step 4: Write `LICENSE` (MIT)**

```
MIT License

Copyright (c) 2026 Mihir Argulkar

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 5: Write `README.md`**

````markdown
# TasteTest

**Tells a coffee chain which stores to test a new drink in, and why, based on what each neighborhood actually likes.**

Live demo: <Render URL> · Built for the [Qloo Agentic Hackathon](https://qloo.devpost.com)

## What it does

1. Describe a limited-time offer in plain language ("matcha-yuzu cold brew, bright and citrusy, for a younger crowd").
2. A Claude agent turns it into a **taste signature**: real Qloo dish/drink tags and place IDs found with `/v2/tags` and `/search`. When a word has no Qloo match, the agent substitutes the closest concept and shows the substitution. Any ID a search didn't return is discarded.
3. Every store is scored from **Qloo heatmaps** (one per metro per concept). Each store takes the affinity of the nearest heatmap point (no point nearby means low interest), weighted across concepts, then z-scored against the chain. Thin data (low Qloo popularity) is flagged, not trusted. Fit is relative to each city.
4. The map shows **where to test and where to skip**, with one-line reasons that cite only Qloo taste tags for each area.
5. **Stability check:** the ranking is recomputed with each concept left out, and the worst-case Spearman ρ is shown, so you can see whether the result hangs on a single tag.
6. Click any store for a **localization brief**: verdict, local taste tags, and local collab partners (nearby Qloo places).

Scores come from deterministic code; the LLM only picks concepts and writes prose. It's a prioritization tool for choosing test stores, not a sales forecast. Not affiliated with any chain shown.

## Run locally

```bash
cd backend && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export QLOO_API_KEY=...  ANTHROPIC_API_KEY=...
uvicorn app.main:app --port 8000
# second terminal
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Tests: `cd backend && pytest`

## Use your own chain

Replace `backend/data/stores.csv` (`id,name,address,lat,lon,metro`; `scripts/geocode.py` fills in lat/lon), set `CHAIN` in `frontend/src/config.js`, and re-run `scripts/precompute_demos.py`.

## License

MIT
````

- [ ] **Step 6: Push to a public GitHub repo**

Ask the user to confirm the repo name and visibility before creating it (publishing is outward-facing).
```bash
gh repo create tastetest --public --source=. --push
```
Then set the repo's About section: description = the one-line pitch, website = the Render URL. GitHub detects the MIT license and shows it in About automatically.

- [ ] **Step 7: Deploy on Render**

In the Render dashboard (user action: it needs their account): New → Blueprint → select the repo. Render reads `render.yaml`. Enter `QLOO_API_KEY` and `ANTHROPIC_API_KEY` when prompted.
Expected: the deploy finishes, and `https://<service>.onrender.com/api/demos` returns 3 demos.

- [ ] **Step 8: Verify the live URL like a judge would**

In a private browser window, on desktop and at phone width:
- The first demo loads with no login.
- All 3 demo pills work, and briefs open instantly.
- One live LTO run completes.
- The 7th live run within an hour shows the rate-limit message and the demos still work.

- [ ] **Step 9: Write the Devpost description**

Save as `docs/devpost.md` and paste it into the submission form:
```markdown
**TasteTest tells a coffee chain which stores to test a new drink in, and why, based on what each neighborhood actually likes.**

Mid-size specialty coffee chains launch limited-time drinks several times a year. With 15–70 stores across several cities, they're too big to know every neighborhood and too small for a data team, so new drinks often get tested in the wrong stores.

**How it's Qloo-powered:** A Claude agent turns a plain-language drink description into a taste signature of real Qloo tags and entities (`/v2/tags`, `/search`), substituting the closest concept when a word has no match. Each store is scored from Qloo heatmaps, one per metro per concept, by reading the affinity at the store's location and z-scoring it against the chain. A leave-one-out stability check (Spearman ρ) shows whether the ranking hangs on any single concept. Per-store briefs (local taste tags, local collab partners from nearby Qloo places) only ever name entities Qloo returned. Without Qloo, there is nothing to rank: an LLM can only guess what a neighborhood likes.

**Try it:** open the demo, pick a preloaded drink, click any store. Or type your own drink. The agent trace at the bottom shows every Qloo call.

Built with FastAPI, Claude (tool use), React, and MapLibre. MIT licensed.
```

- [ ] **Step 10: Commit and push**

```bash
git add Dockerfile .dockerignore render.yaml LICENSE README.md docs/devpost.md
git commit -m "chore: Docker + Render deploy, MIT license, README, Devpost text"
git push
```

---

### Task 14 (optional, if time allows): Framer landing page

Manual work in Framer. No code in the repo.

- [ ] **Step 1:** Create a new Framer site. Hero: the one-line pitch in large type (marketplace "Text Reveal"), with a subline: "For coffee chains launching their next limited-time drink."
- [ ] **Step 2:** Add "Multi Location Map" or "Dotted Globe" from the marketplace with pins on the chain's metros.
- [ ] **Step 3:** Add three short "How it works" tiles (Describe → Score → Brief), each with a screenshot of the live app.
- [ ] **Step 4:** Add a primary "Try the live demo" button linking to the Render URL, plus a GitHub link.
- [ ] **Step 5:** Publish on a framer.website subdomain and link it from the README and the Devpost "Try it out" links.

---

## Self-review notes

- **Spec coverage:**
  - §1 pitch → README and Devpost text (Task 13)
  - §2 Philz and the per-metro coverage rule → Task 11; brand guardrails → `CHAIN` footer copy (Task 8)
  - §3.1 dish-tag/place-only signature → Tasks 4–5; §3.2 sparse-cell scoring → Task 3; §3.3 confidence → Task 3; §3.4 leave-one-out stability → Tasks 3, 4 and 8
  - §4 tools, 25-call cap, follow-ups → Tasks 4–5, refine input in Task 8
  - §5 UI, no playlist → Tasks 7–9
  - §6 architecture/hosting → Tasks 6 and 13
  - §7 reliability → precomputed demos (Task 12), disk cache + 429 back-off (Task 1), errors as data (Task 5), rate limit (Task 6), in-stream error toast (Task 7), `test_scoring.py` (Task 3), `coverage_check.py` (Task 11)
  - §8 checklist → Task 13; Framer → Task 14
- **Changed after the 2026-10-06 live probe:** heatmaps only work for specialty-dish tags and place entities; Philadelphia has no data (so Philz); cells are sparse (missing nearby = low affinity); the nearby-places check was replaced by leave-one-out stability; playlist removed; concurrency 3 with 429 back-off; `/search` uses `types`.
- **Deliberate deviation from spec §4 step 4 (unchanged):** per-store evidence is gathered by code inside `run_score`, and the LLM writes all reasons in one structured call.
