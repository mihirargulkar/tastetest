"""The agent's tools: thin wrappers over Qloo + the store list."""
import asyncio

from .scoring import score, stability

RADIUS_M = 1200
# The only tag type the hackathon API returns heatmaps for (live probe, 2026-10-06).
HEATMAP_TAG_PREFIX = "urn:tag:specialty_dish:place:"
MAX_TAGS = 5  # heatmap calls per find_tags


class Tools:
    def __init__(self, qloo, stores: list[dict], regions: dict[str, str] | None = None):
        self.qloo = qloo
        self.regions = regions or {}
        self.stores = stores
        self._by_id = {s["id"]: s for s in stores}

    def store(self, store_id: str) -> dict:
        return self._by_id[store_id]

    async def find_tags(self, query: str) -> list[dict]:
        tags = [t for t in await self.qloo.search_tags(query) if t["id"].startswith(HEATMAP_TAG_PREFIX)]
        if not self.regions:
            return tags
        tags = tags[:MAX_TAGS]
        wkts = list(self.regions.values())
        counts = await asyncio.gather(*(self.qloo.heatmap({"id": t["id"], "kind": "tag"}, w) for t in tags for w in wkts),
                                      return_exceptions=True)
        out = []
        for i, t in enumerate(tags):
            part = counts[i * len(wkts):(i + 1) * len(wkts)]
            cells = sum(0 if isinstance(c, Exception) else len(c) for c in part)
            if cells:
                out.append({**t, "cells": cells})
        return sorted(out, key=lambda t: -t["cells"])

    async def find_places(self, query: str) -> list[dict]:
        return await self.qloo.search_places(query)

    async def score_stores(self, signature: list[dict]) -> dict:
        items = [i for i in signature if i["weight"] > 0]
        metros = sorted({s["metro"] for s in self.stores})
        pairs = [(m, i) for m in metros for i in items]
        results = await asyncio.gather(*(self.qloo.heatmap(i, self.regions.get(m, m)) for m, i in pairs),
                                       return_exceptions=True)
        if results and all(isinstance(r, Exception) for r in results):
            raise results[0]
        by_metro = {m: {} for m in metros}
        for (m, i), cells in zip(pairs, results):
            by_metro[m][i["id"]] = [] if isinstance(cells, Exception) else cells
        weights = {i["id"]: i["weight"] for i in items}
        return {"stores": score(self.stores, by_metro, weights),
                "stability": stability(self.stores, by_metro, weights)}

    async def area_taste(self, store_id: str) -> dict:
        s = self.store(store_id)
        parts = await asyncio.gather(self.qloo.area_tags(s["lat"], s["lon"], RADIUS_M),
                                     self.qloo.area_places(s["lat"], s["lon"], RADIUS_M), return_exceptions=True)
        tags, places = [[] if isinstance(p, Exception) else p for p in parts]
        return {"tags": tags, "places": places}
