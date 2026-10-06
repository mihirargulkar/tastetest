"""Which Philz stores have enough Qloo heatmap data to include in the demo?

Usage (from backend/): python scripts/coverage_check.py data/candidates/philz.csv [--write data/stores.csv]
For each polygon in data/regions.json, fetches the heatmap of each reference tag, assigns every candidate store to the
first region whose bounding box contains it, and counts stores with a cell within MAX_CELL_KM for either tag.
--write saves the covered stores, with metro set to the region name.
"""
import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.qloo import Qloo, QlooError  # noqa: E402
from app.scoring import MAX_CELL_KM, nearest_cell  # noqa: E402
from app.stores import load_stores  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"
REFERENCE_TAGS = ["urn:tag:specialty_dish:place:matcha", "urn:tag:specialty_dish:place:coffee"]


def bbox(wkt: str) -> tuple[float, float, float, float]:  # polygons are axis-aligned boxes
    pts = [tuple(map(float, p.split())) for p in re.findall(r"(-?[\d.]+ -?[\d.]+)", wkt)]
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    return min(lons), min(lats), max(lons), max(lats)


def first_region(s: dict, boxes: dict) -> str | None:
    return next((r for r, b in boxes.items() if b[0] <= s["lon"] <= b[2] and b[1] <= s["lat"] <= b[3]), None)


async def main(src: str, write_to: str | None) -> None:
    q = Qloo(os.environ["QLOO_API_KEY"], DATA / "cache")
    regions = json.loads((DATA / "regions.json").read_text())
    boxes = {name: bbox(w) for name, w in regions.items()}
    stores = load_stores(Path(src))
    keep = []
    names = [t.rsplit(":", 1)[-1] for t in REFERENCE_TAGS]
    print(f"{'region':<12}{'in box':>8}{'covered':>9}" + "".join(f"{n + ' cells':>16}" for n in names))
    for name, wkt in regions.items():
        in_box = [s for s in stores if first_region(s, boxes) == name]
        heat = []
        for tag in REFERENCE_TAGS:  # sequential on purpose: the API rate-limits bursts
            try:
                heat.append(await q.heatmap({"id": tag, "kind": "tag"}, wkt))
            except QlooError:
                heat.append([])
        covered = [s for s in in_box if any(nearest_cell(c, s["lat"], s["lon"], MAX_CELL_KM) is not None for c in heat)]
        print(f"{name:<12}{len(in_box):>8}{len(covered):>9}" + "".join(f"{len(c):>16}" for c in heat))
        keep += [{**s, "metro": name} for s in covered]
    if write_to:
        with open(write_to, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "name", "address", "lat", "lon", "metro"])
            w.writeheader()
            w.writerows(keep)
        print(f"wrote {len(keep)} stores to {write_to}")


if __name__ == "__main__":
    args = sys.argv[1:]
    asyncio.run(main(args[0], args[args.index("--write") + 1] if "--write" in args else None))
