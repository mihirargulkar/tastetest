import json

import pytest
from fastapi.testclient import TestClient

from app import agent, main
from app.agent import AgentError

STORES = [{"id": "a", "name": "A", "address": "x", "lat": 0.0, "lon": 0.0, "metro": "M"}]
SIG = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]


class FakeTools:
    stores = STORES

    def store(self, store_id):
        return {s["id"]: s for s in STORES}[store_id]


@pytest.fixture
def client(tmp_path, monkeypatch):
    main._hits.clear()
    main.app.state.tools = FakeTools()
    main.app.state.llm = object()
    monkeypatch.setattr(main, "DEMOS", tmp_path)
    (tmp_path / "matcha.json").write_text(json.dumps({"slug": "matcha", "title": "Matcha", "lto": "m"}))
    return TestClient(main.app)


def events(response):
    return [json.loads(line[6:]) for line in response.text.split("\n\n") if line.startswith("data: ")]


def test_stores(client, monkeypatch):
    monkeypatch.setattr(main, "STORES", STORES)
    assert client.get("/api/stores").json() == STORES


def test_demos_list_and_get(client):
    assert client.get("/api/demos").json() == [{"slug": "matcha", "title": "Matcha", "lto": "m"}]
    assert client.get("/api/demos/matcha").json()["title"] == "Matcha"
    assert client.get("/api/demos/..%2Fsecrets").status_code == 404
    assert client.get("/api/demos/nope").status_code == 404


def test_signature_streams_events(client, monkeypatch):
    async def fake(llm, tools, lto, current=None, instruction=None):
        yield {"type": "trace", "tool": "find_tags", "args": {"query": lto}, "summary": "1 results"}
        yield {"type": "signature", "items": SIG, "dropped": 0}

    monkeypatch.setattr(agent, "build_signature", fake)
    r = client.post("/api/signature", json={"lto": "matcha"})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert [e["type"] for e in events(r)] == ["trace", "signature"]
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"


def test_errors_are_sent_in_stream(client, monkeypatch):
    async def fake(llm, tools, signature):
        raise AgentError("the model declined this request")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "run_score", fake)
    r = client.post("/api/score", json={"signature": SIG})
    assert events(r) == [{"type": "error", "message": "the model declined this request"}]


def test_validation_rejects_bad_input(client):
    assert client.post("/api/signature", json={"lto": "x" * 501}).status_code == 422
    assert client.post("/api/score", json={"signature": []}).status_code == 422
    bad = [{**SIG[0], "weight": 3}]
    assert client.post("/api/score", json={"signature": bad}).status_code == 422


def test_rate_limit(client, monkeypatch):
    async def fake(llm, tools, signature):
        yield {"type": "result"}

    monkeypatch.setattr(agent, "run_score", fake)
    codes = [client.post("/api/score", json={"signature": SIG}).status_code for _ in range(7)]
    assert codes == [200] * 6 + [429]


def test_brief_unknown_store_404(client, monkeypatch):
    async def fake(llm, tools, store_id, signature, fit):
        tools.store(store_id)

    monkeypatch.setattr(agent, "write_brief", fake)
    assert client.post("/api/brief", json={"store_id": "zzz", "signature": SIG, "fit": None}).status_code == 404


def _ok_score(monkeypatch):
    async def fake(llm, tools, signature):
        yield {"type": "result"}

    monkeypatch.setattr(agent, "run_score", fake)


def test_rate_limit_ignores_spoofed_leftmost_xff(client, monkeypatch):
    _ok_score(monkeypatch)
    codes = [
        client.post("/api/score", json={"signature": SIG}, headers={"X-Forwarded-For": f"spoof{i}, 1.2.3.4"}).status_code
        for i in range(7)
    ]
    assert codes[-1] == 429


def test_global_live_ceiling_across_ips(client, monkeypatch):
    _ok_score(monkeypatch)
    monkeypatch.setattr(main, "GLOBAL_LIVE_PER_HOUR", 3)
    codes = [
        client.post("/api/score", json={"signature": SIG}, headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code
        for i in range(4)
    ]
    assert codes == [200, 200, 200, 429]


def test_unexpected_error_text_hidden_from_stream(client, monkeypatch):
    async def fake(llm, tools, signature):
        raise RuntimeError("secret upstream body")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "run_score", fake)
    r = client.post("/api/score", json={"signature": SIG})
    assert "secret upstream body" not in r.text
    assert events(r) == [{"type": "error", "message": "Something went wrong. Try one of the preloaded examples."}]


def test_global_daily_ceiling_across_ips(client, monkeypatch):
    _ok_score(monkeypatch)
    monkeypatch.setattr(main, "GLOBAL_LIVE_PER_DAY", 2)
    monkeypatch.setattr(main, "GLOBAL_LIVE_PER_HOUR", 1000)
    codes = [
        client.post("/api/score", json={"signature": SIG}, headers={"X-Forwarded-For": f"8.8.8.{i}"}).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


def test_demos_and_stores_load_without_keys(monkeypatch):
    for a in ("tools", "llm"):
        if hasattr(main.app.state, a):
            delattr(main.app.state, a)
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(main, "DEMOS", main.DATA / "demos")
    c = TestClient(main.app)
    assert len(c.get("/api/stores").json()) == 40
    listed = c.get("/api/demos").json()
    assert len(listed) == 3
    assert all(c.get(f"/api/demos/{d['slug']}").status_code == 200 for d in listed)
    assert not hasattr(main.app.state, "tools")


def test_global_brief_daily_ceiling_across_ips(client, monkeypatch):
    async def fake(llm, tools, store_id, signature, fit):
        return {"brief": "ok"}

    monkeypatch.setattr(agent, "write_brief", fake)
    monkeypatch.setattr(main, "GLOBAL_BRIEFS_PER_DAY", 2)
    codes = [
        client.post("/api/brief", json={"store_id": "a", "signature": SIG, "fit": None},
                    headers={"X-Forwarded-For": f"7.7.7.{i}"}).status_code
        for i in range(3)
    ]
    assert 429 not in codes[:2] and codes[2] == 429


def test_live_mode_off_pauses_live_but_not_demos(client, monkeypatch):
    monkeypatch.setattr(main, "LIVE_MODE", False)
    r = client.post("/api/score", json={"signature": SIG})
    assert r.status_code == 503
    assert r.json()["detail"] == "Live runs are paused. The preloaded examples still work."
    assert client.get("/api/demos").status_code == 200
