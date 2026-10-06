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


def _baseline_affinity(store: dict, baseline_lists: list[list[dict]]) -> float | None:
    """Unweighted mean nearest-cell affinity over the baseline tags, same sparse-cell rules as _store_affinity."""
    affs = [(c["affinity"] if (c := nearest_cell(cells, store["lat"], store["lon"])) else 0.0)
            for cells in baseline_lists if cells]
    return mean(affs) if affs else None


def score(stores: list[dict], cells_by_metro: dict, weights: dict, baseline_by_metro: dict | None = None) -> list[dict]:
    rows = []
    for s in stores:
        aff, pop = _store_affinity(s, cells_by_metro.get(s["metro"], {}), weights)
        base = _baseline_affinity(s, baseline_by_metro.get(s["metro"], [])) if baseline_by_metro else None
        lift = None if aff is None else aff if base is None else aff - base
        rows.append({**s, "affinity": aff, "popularity": pop, "baseline": base, "lift": lift})
    vals = [r["lift"] for r in rows if r["lift"] is not None]
    mu = mean(vals) if vals else 0.0
    sd = pstdev(vals) if len(vals) > 1 else 0.0
    for r in rows:
        if r["affinity"] is None:
            r["fit"], r["confidence"] = None, "none"
        else:
            r["fit"] = round((r["lift"] - mu) / sd, 2) if sd else 0.0
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


def stability(stores: list[dict], cells_by_metro: dict, weights: dict, baseline_by_metro: dict | None = None) -> dict | None:
    """Leave-one-out: how much does the ranking move when any single concept is dropped? Reports the worst case."""
    if len(weights) < 2:
        return None
    full = {s["id"]: s["fit"] for s in score(stores, cells_by_metro, weights, baseline_by_metro)}
    worst = None
    for item_id in weights:
        w2 = {k: v for k, v in weights.items() if k != item_id}
        c2 = {m: {k: v for k, v in items.items() if k != item_id} for m, items in cells_by_metro.items()}
        reduced = {s["id"]: s["fit"] for s in score(stores, c2, w2, baseline_by_metro)}
        ids = [i for i in full if full[i] is not None and reduced.get(i) is not None]
        rho = spearman([full[i] for i in ids], [reduced[i] for i in ids])
        if rho is not None and (worst is None or rho < worst[0]):
            worst = (rho, item_id)
    return {"rho": round(worst[0], 2), "weakest": worst[1]} if worst else None
