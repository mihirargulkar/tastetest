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


def _store_affinity(store: dict, cells_by_item: dict, weights: dict):
    """Weighted mean nearest-cell affinity over the items with a usable cell.

    An item is skipped (None) when the city has no cells for it or no cell lies within MAX_CELL_KM of the store:
    missing data is missing, not zero. Returns (affinity, popularity, per-item affinities).
    """
    items = {item_id: None for item_id in cells_by_item}
    hits = []  # (weight, affinity, popularity)
    for item_id, cells in cells_by_item.items():
        c = nearest_cell(cells, store["lat"], store["lon"]) if cells else None
        if c:
            items[item_id] = c["affinity"]
            hits.append((weights[item_id], c["affinity"], c["popularity"]))
    total = sum(w for w, _, _ in hits)
    if total == 0:
        return None, None, items
    return sum(w * a for w, a, _ in hits) / total, mean(p for _, _, p in hits), items


def score(stores: list[dict], cells_by_metro: dict, weights: dict) -> list[dict]:
    """fit = z-score of weighted nearest-cell affinity across the chain; `items` gives each item's affinity per store."""
    rows = []
    for s in stores:
        aff, pop, items = _store_affinity(s, cells_by_metro.get(s["metro"], {}), weights)
        rows.append({**s, "affinity": aff, "popularity": pop, "items": items})
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
