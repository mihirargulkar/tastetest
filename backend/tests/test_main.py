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


def test_stores(client):
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
