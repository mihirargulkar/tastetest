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
