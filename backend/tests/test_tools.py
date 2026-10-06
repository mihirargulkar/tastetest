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
    assert set(q.heatmap_calls) == {("T1", "M1"), ("T1", "M2")}
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


async def test_score_stores_sends_region_wkt_to_heatmap():
    q = FakeQloo()
    t = Tools(q, STORES, regions={"M1": "POLYGON((M1))"})
    q.heatmap = lambda item, area: _wkt_heatmap(q, item, area)
    await t.score_stores(SIG)
    assert set(q.heatmap_calls) == {("T1", "M2"), ("T1", "POLYGON((M1))")}


async def _wkt_heatmap(q, item, area):
    q.heatmap_calls.append((item["id"], area))
    return []


class TagQloo:
    CELLS = {"t1": 5, "t2": 0, "t3": 30, "t4": 1, "t5": 2, "t6": 99}

    async def search_tags(self, query, take=10):
        return [{"id": f"urn:tag:specialty_dish:place:{k}", "name": k, "type": "x"} for k in self.CELLS]

    async def heatmap(self, item, area):
        n = self.CELLS[item["id"].rsplit(":", 1)[-1]]
        if area == "bad":
            raise QlooError(500, "boom")
        return [{"lat": 0, "lon": 0, "affinity": 0.5, "popularity": 0.5}] * (n // 2 + n % 2 if area == "W1" else n // 2)


async def test_find_tags_annotates_cells_drops_empty_sorts_and_caps_at_5():
    tags = await Tools(TagQloo(), STORES, regions={"R1": "W1", "R2": "W2"}).find_tags("x")
    # first 5 only (t6 excluded); t2 has 0 cells and is dropped; sorted by cells desc
    assert [(t["name"], t["cells"]) for t in tags] == [("t3", 30), ("t1", 5), ("t5", 2), ("t4", 1)]


async def test_find_tags_counts_failed_region_as_zero():
    tags = await Tools(TagQloo(), STORES, regions={"R1": "W1", "R2": "bad"}).find_tags("x")
    assert tags and all(t["cells"] > 0 for t in tags)
