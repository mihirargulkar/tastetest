import csv
from pathlib import Path


def load_stores(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return [{"id": r["id"], "name": r["name"], "address": r["address"],
                 "lat": float(r["lat"]), "lon": float(r["lon"]), "metro": r["metro"]}
                for r in csv.DictReader(f)]
