"""Thin async Qloo client: disk cache + response parsing. Every Qloo response shape lives in this file."""
import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

import httpx

BASE_URL = "https://hackathon.api.qloo.com"
MAX_RETRIES = 3
_sleep = asyncio.sleep  # indirection so tests can skip real waits


PARTNER_CATEGORY_TAGS = ",".join([
    "urn:tag:category:place:bakery",
    "urn:tag:category:place:dessert_shop",
    "urn:tag:category:place:tea_house",
    "urn:tag:category:place:book_store",
    "urn:tag:category:place:ice_cream_shop",
])


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
            try:
                return json.loads(f.read_text())
            except json.JSONDecodeError:
                pass  # corrupt cache file: treat as a miss and overwrite
        for attempt in range(MAX_RETRIES + 1):
            async with self.sem:
                r = await self.http.get(path, params=params, headers={"X-Api-Key": self.api_key})
            if r.status_code != 429 or attempt == MAX_RETRIES:
                break
            await _sleep(float(r.headers.get("retry-after", 2 ** (attempt + 1))))
        if r.status_code != 200:
            raise QlooError(r.status_code, r.text)
        data = r.json()
        with tempfile.NamedTemporaryFile("w", dir=f.parent, suffix=".tmp", delete=False) as t:
            t.write(json.dumps(data))
        os.replace(t.name, f)
        return data

    async def search_tags(self, query: str, take: int = 10) -> list[dict]:
        return parse_tag_search(await self.get("/v2/tags", {"filter.query": query, "take": take}))

    async def search_places(self, query: str, take: int = 5) -> list[dict]:
        return parse_search(await self.get("/search", {"query": query, "types": "urn:entity:place", "take": take}))

    async def heatmap(self, item: dict, area: str) -> list[dict]:
        key = "signal.interests.tags" if item["kind"] == "tag" else "signal.interests.entities"
        loc = "filter.location" if area.startswith(("POLYGON", "MULTIPOLYGON")) else "filter.location.query"
        return parse_heatmap(await self.get("/v2/insights", {"filter.type": "urn:heatmap", loc: area, key: item["id"]}))

    async def area_tags(self, lat: float, lon: float, radius_m: int, take: int = 10) -> list[dict]:
        return parse_area_tags(await self.get("/v2/insights", {
            "filter.type": "urn:tag", "signal.location": point(lat, lon),
            "signal.location.radius": radius_m, "take": take}))

    async def area_places(self, lat: float, lon: float, radius_m: int, take: int = 5) -> list[dict]:
        return parse_entities(await self.get("/v2/insights", {
            "filter.type": "urn:entity:place", "filter.location": point(lat, lon),
            "filter.location.radius": radius_m, "filter.tags": PARTNER_CATEGORY_TAGS, "take": take}))
