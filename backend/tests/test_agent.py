import json
from types import SimpleNamespace as NS

import pytest

from app import agent
from app.agent import AgentError, build_signature, run_score, run_tool_loop, write_brief


def tool_use(id, name, input):
    return NS(type="tool_use", id=id, name=name, input=input)


def text(t):
    return NS(type="text", text=t)


def resp(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop)


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    async def _create(self, **kw):
        # Snapshot messages: the loop keeps appending to the same list after this call returns.
        self.calls.append({**kw, "messages": list(kw.get("messages", []))})
        return self.responses.pop(0)


class FakeTools:
    stores = [{"id": s, "name": s, "address": "", "lat": 0, "lon": 0, "metro": "M"} for s in "abcd"]

    async def find_tags(self, query):
        return [{"id": "T-" + query, "name": query}]

    async def find_places(self, query):
        return []

    async def score_stores(self, signature):
        fits = {"a": 1.5, "b": 0.5, "c": -0.5, "d": -1.5}
        return {"stores": [{**s, "fit": fits[s["id"]], "confidence": "high"} for s in self.stores],
                "stability": {"rho": 0.86, "weakest": "T1"}}

    async def area_taste(self, store_id):
        return {"tags": [{"id": "T9", "name": "japanese cafe", "affinity": 0.9}],
                "places": [{"id": "P1", "name": "Tea Shop", "affinity": 0.8, "image": None}]}

    def store(self, store_id):
        return next(s for s in self.stores if s["id"] == store_id)


async def collect(gen):
    return [ev async for ev in gen]


async def test_build_signature_drops_invented_ids():
    llm = FakeLLM([
        resp(tool_use("t1", "find_tags", {"query": "matcha"})),
        resp(tool_use("t2", "submit_signature", {"items": [
            {"id": "T-matcha", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None},
            {"id": "T-invented", "name": "fake", "kind": "tag", "weight": 0.5, "substituted_from": None}]})),
    ])
    events = await collect(build_signature(llm, FakeTools(), "matcha latte"))
    assert events[0]["type"] == "trace" and events[0]["tool"] == "find_tags"
    assert events[-1] == {"type": "signature", "dropped": 1, "items": [
        {"id": "T-matcha", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]}
    assert llm.calls[0]["model"] == "claude-sonnet-5-5"
    assert llm.calls[0]["fallbacks"] == "default"
    assert "tool_choice" not in llm.calls[0]


async def test_signature_names_and_kinds_come_from_qloo():
    llm = FakeLLM([
        resp(tool_use("t1", "find_tags", {"query": "matcha"})),
        resp(tool_use("t2", "submit_signature", {"items": [
            {"id": "T-matcha", "name": "Invented Name", "kind": "entity", "weight": 1.0, "substituted_from": None}]})),
    ])
    events = await collect(build_signature(llm, FakeTools(), "matcha latte"))
    item = events[-1]["items"][0]
    assert (item["name"], item["kind"]) == ("matcha", "tag")


async def test_refinement_keeps_current_ids():
    current = [{"id": "T-old", "name": "old", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    llm = FakeLLM([resp(tool_use("t1", "submit_signature", {"items": current}))])
    events = await collect(build_signature(llm, FakeTools(), "x", current=current, instruction="keep it"))
    assert events[-1]["items"] == current


async def test_tool_errors_are_reported_back_and_loop_continues():
    async def boom(query):
        raise TypeError("bad args")

    llm = FakeLLM([resp(tool_use("t1", "find_tags", {"query": "x"})),
                   resp(tool_use("t2", "done", {"ok": True}))])
    events = await collect(run_tool_loop(llm, system="s", user="u", tools=[], handlers={"find_tags": boom},
                                         finish_tool="done"))
    assert events[0]["summary"].startswith("error")
    tool_result = llm.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert events[-1] == {"type": "finish", "input": {"ok": True}}


async def test_tool_call_cap():
    async def find(query):
        return []

    llm = FakeLLM([resp(tool_use(f"t{i}", "find_tags", {"query": "x"})) for i in range(5)])
    with pytest.raises(AgentError, match="cap"):
        await collect(run_tool_loop(llm, system="s", user="u", tools=[], handlers={"find_tags": find},
                                    finish_tool="done", max_calls=2))


async def test_refusal_raises():
    llm = FakeLLM([resp(text("no"), stop="refusal")])
    with pytest.raises(AgentError, match="declined"):
        await collect(build_signature(llm, FakeTools(), "x"))


async def test_stopping_without_finish_raises():
    llm = FakeLLM([resp(text("I am done"), stop="end_turn")])
    with pytest.raises(AgentError, match="submit_signature"):
        await collect(build_signature(llm, FakeTools(), "x"))


async def test_run_score_result_event():
    reasons = {"reasons": [{"store_id": "a", "reason": "Leans into japanese cafe culture."}]}
    llm = FakeLLM([resp(text(json.dumps(reasons)), stop="end_turn")])
    sig = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    events = await collect(run_score(llm, FakeTools(), sig))
    result = events[-1]
    assert result["type"] == "result"
    assert result["top"] == ["a", "b", "c", "d"]  # 4 stores: all fit in the top 5
    assert result["bottom"] == []
    assert result["reasons"]["a"] == "Leans into japanese cafe culture."
    assert result["reasons"]["d"] == "Over-indexes on japanese cafe."  # deterministic fallback
    assert result["stability"] == {"rho": 0.86, "weakest": "matcha"}  # item id mapped to its name
    assert any(e["type"] == "trace" and e["tool"] == "score_stores" for e in events)


async def test_run_score_skip_group_and_no_stability():
    class EightStores(FakeTools):
        stores = [{"id": s, "name": s, "address": "", "lat": 0, "lon": 0, "metro": "M"} for s in "abcdefgh"]

        async def score_stores(self, signature):
            return {"stores": [{**s, "fit": 2.0 - i * 0.5, "confidence": "high"} for i, s in enumerate(self.stores)],
                    "stability": None}

    llm = FakeLLM([resp(text(json.dumps({"reasons": []})), stop="end_turn")])
    sig = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    result = (await collect(run_score(llm, EightStores(), sig)))[-1]
    assert result["bottom"] == ["h", "g", "f"]
    assert result["stability"] is None


async def test_run_score_reason_fallback_when_llm_fails():
    llm = FakeLLM([resp(text("no"), stop="refusal")])
    sig = [{"id": "E1", "name": "Some Brand", "kind": "entity", "weight": 1.0, "substituted_from": None}]
    events = await collect(run_score(llm, FakeTools(), sig))
    assert events[-1]["reasons"]["a"] == "Over-indexes on japanese cafe."


async def test_write_brief_uses_only_qloo_entities():
    out = {"verdict": "The neighborhood leans into Japanese cafe culture.", "menu_cues": ["Lead with matcha"]}
    llm = FakeLLM([resp(text(json.dumps(out)), stop="end_turn")])
    sig = [{"id": "T1", "name": "matcha", "kind": "tag", "weight": 1.0, "substituted_from": None}]
    brief = await write_brief(llm, FakeTools(), "a", sig, 1.5)
    assert brief["label"] == "test"
    assert "artists" not in brief  # no playlist: location-based artists aren't demo-safe
    assert brief["partners"][0]["name"] == "Tea Shop"
    assert brief["verdict"].startswith("The neighborhood")
    assert brief["menu_cues"] == ["Lead with matcha"]
