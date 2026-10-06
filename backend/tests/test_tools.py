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
    assert sorted(q.heatmap_calls) == [("T1", "M1"), ("T1", "M2")]
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
