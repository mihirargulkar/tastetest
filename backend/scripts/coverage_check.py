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
