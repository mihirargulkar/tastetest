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
