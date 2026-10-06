import httpx
import pytest

from app import qloo
from app.qloo import (BASE_URL, Qloo, QlooError, cache_key, parse_area_tags, parse_entities,
                      parse_heatmap, parse_search, parse_tag_search, point)


def make_client(tmp_path, handler):
    http = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return Qloo("test-key", tmp_path, http=http)


def test_point_is_lon_first():
    assert point(40.7, -73.9) == "POINT(-73.9 40.7)"


def test_cache_key_ignores_param_order():
    assert cache_key("/v2/insights", {"a": 1, "b": 2}) == cache_key("/v2/insights", {"b": 2, "a": 1})


async def test_get_sends_key_and_caches(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"results": {"tags": []}})

    q = make_client(tmp_path, handler)
    await q.get("/v2/tags", {"filter.query": "matcha"})
    await q.get("/v2/tags", {"filter.query": "matcha"})
    assert len(calls) == 1
    assert calls[0].headers["X-Api-Key"] == "test-key"


async def test_corrupt_cache_file_is_a_miss(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": 1})

    q = make_client(tmp_path, handler)
    params = {"filter.query": "matcha"}
    (tmp_path / f"{cache_key('/v2/tags', params)}.json").write_text('{"trunc')
    assert await q.get("/v2/tags", params) == {"ok": 1}
    assert await q.get("/v2/tags", params) == {"ok": 1}
    assert len(calls) == 1


async def test_errors_raise_and_are_not_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, text="forbidden")

    q = make_client(tmp_path, handler)
    for _ in range(2):
        with pytest.raises(QlooError) as e:
            await q.get("/v2/insights", {"filter.type": "urn:entity:music"})
        assert e.value.status == 403
    assert len(calls) == 2


async def test_heatmap_uses_tags_or_entities_param(tmp_path):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": {"heatmap": []}})

    q = make_client(tmp_path, handler)
    await q.heatmap({"id": "T1", "kind": "tag", "weight": 1}, "Brooklyn")
    await q.heatmap({"id": "E1", "kind": "entity", "weight": 1}, "Brooklyn")
    assert seen[0]["signal.interests.tags"] == "T1"
    assert seen[1]["signal.interests.entities"] == "E1"
    assert seen[0]["filter.type"] == "urn:heatmap"
    assert seen[0]["filter.location.query"] == "Brooklyn"


async def test_area_queries_use_point_location(tmp_path):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": {"entities": [], "tags": []}})

    q = make_client(tmp_path, handler)
    await q.area_places(40.7, -73.9, 1200)
    await q.area_tags(40.7, -73.9, 1200)
    assert seen[0]["filter.type"] == "urn:entity:place"
    assert seen[0]["filter.location"] == "POINT(-73.9 40.7)"
    assert seen[1]["filter.type"] == "urn:tag"
    assert seen[1]["signal.location"] == "POINT(-73.9 40.7)"


async def test_retries_429_then_succeeds(tmp_path, monkeypatch):
    statuses = [429, 429, 200]
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    def handler(request):
        code = statuses.pop(0)
        return httpx.Response(code, json={"results": {"tags": []}}, headers={"retry-after": "1"} if code == 429 else {})

    monkeypatch.setattr(qloo, "_sleep", fake_sleep)
    q = make_client(tmp_path, handler)
    assert await q.get("/v2/tags", {"filter.query": "x"}) == {"results": {"tags": []}}
    assert slept == [1.0, 1.0]


def test_parsers():
    assert parse_tag_search({"results": {"tags": [{"id": "T1", "name": "Matcha", "type": "urn:tag:specialty_dish:place"}]}}) == [
        {"id": "T1", "name": "Matcha", "type": "urn:tag:specialty_dish:place"}]
    assert parse_search({"results": [{"entity_id": "E1", "name": "Cafe", "types": ["urn:entity:place"]}]}) == [
        {"id": "E1", "name": "Cafe", "type": "urn:entity:place"}]
    assert parse_entities({"results": {"entities": [{"entity_id": "E1", "name": "Khruangbin", "query": {"affinity": 0.9},
                                                       "properties": {"image": {"url": "http://img"}}}]}}) == [
        {"id": "E1", "name": "Khruangbin", "affinity": 0.9, "image": "http://img"}]
    assert parse_area_tags({"results": {"tags": [{"tag_id": "T1", "name": "matcha", "query": {"affinity": 0.7}}]}}) == [
        {"id": "T1", "name": "matcha", "affinity": 0.7}]
    assert parse_heatmap({"results": {"heatmap": [{"location": {"latitude": 1.0, "longitude": 2.0},
                                                    "query": {"affinity": 0.5, "popularity": 0.4}}]}}) == [
        {"lat": 1.0, "lon": 2.0, "affinity": 0.5, "popularity": 0.4}]


async def test_heatmap_polygon_area_goes_to_filter_location(tmp_path):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"results": {"heatmap": []}})

    q = make_client(tmp_path, handler)
    wkt = "POLYGON((0 0,1 0,1 1,0 1,0 0))"
    await q.heatmap({"id": "T1", "kind": "tag"}, wkt)
    await q.heatmap({"id": "T1", "kind": "tag"}, "Brooklyn")
    assert seen[0]["filter.location"] == wkt and "filter.location.query" not in seen[0]
    assert seen[1]["filter.location.query"] == "Brooklyn" and "filter.location" not in seen[1]
