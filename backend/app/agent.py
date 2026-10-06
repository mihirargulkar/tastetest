"""Claude-side logic. The LLM picks Qloo concepts and writes prose; scores come from deterministic code."""
import asyncio
import json

from .qloo import QlooError
from .scoring import pick

MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_CALLS = 25


class AgentError(Exception):
    pass


def trace(tool: str, args: dict, summary: str) -> dict:
    return {"type": "trace", "tool": tool, "args": args, "summary": summary}


def _summarize(out) -> str:
    if isinstance(out, list):
        names = [o.get("name", "?") for o in out[:3] if isinstance(o, dict)]
        return f"{len(out)} results" + (": " + ", ".join(names) if names else "")
    return str(out)[:120]


async def create(llm, *, output_config: dict | None = None, **kw):
    resp = await llm.beta.messages.create(
        model=MODEL, max_tokens=16000, betas=[FALLBACK_BETA], fallbacks="default",
        output_config={"effort": "medium", **(output_config or {})}, **kw)
    if resp.stop_reason == "refusal":
        raise AgentError("the model declined this request")
    return resp


def _text(resp) -> str:
    t = next((b.text for b in resp.content if b.type == "text"), None)
    if t is None:
        raise AgentError("model returned no text")
    return t


async def run_tool_loop(llm, *, system: str, user: str, tools: list, handlers: dict, finish_tool: str,
                        max_calls: int = MAX_TOOL_CALLS):
    messages = [{"role": "user", "content": user}]
    calls = 0
    while True:
        resp = await create(llm, system=system, tools=tools, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            raise AgentError(f"agent stopped without calling {finish_tool}")
        results = []
        for u in uses:
            if u.name == finish_tool:
                yield {"type": "finish", "input": u.input}
                return
            calls += 1
            if calls > max_calls:
                raise AgentError(f"hit the {max_calls}-call cap")
            try:
                out = await handlers[u.name](**u.input)
                summary, is_error = _summarize(out), False
            except (QlooError, KeyError, TypeError) as e:
                out, summary, is_error = {"error": str(e)}, f"error: {e}", True
            yield trace(u.name, u.input, summary)
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out),
                            "is_error": is_error})
        messages.append({"role": "user", "content": results})


# --- Taste signature -------------------------------------------------------------------------

SIGNATURE_SYSTEM = """You turn a coffee chain's limited-time offer (LTO) description into a Qloo taste signature.

1. Break the description into 3-8 concepts that are dishes, drinks, or ingredients (e.g. "matcha latte", "yuzu", "cold brew"). Express the vibe of the target customer through such items or through a well-known place that embodies it.
2. Resolve every concept to a real Qloo ID with find_tags (preferred; it only returns dish and drink tags) or find_places. If a search returns nothing useful, try a broader or synonymous term and put the original word in substituted_from.
3. Weight each item from 0.1 to 1.0 by how central it is to the product.
4. Finish by calling submit_signature exactly once, using only IDs that a search returned. Never invent IDs.

If you are given a current signature and an instruction, edit the signature to satisfy the instruction (search for new concepts as needed) and submit the full updated signature."""

_STR = {"type": "string"}
SIGNATURE_TOOLS = [
    {"name": "find_tags", "strict": True,
     "description": "Search Qloo tags (flavors, cuisines, genres, styles, scenes) by keyword. Returns [{id, name}].",
     "input_schema": {"type": "object", "properties": {"query": _STR}, "required": ["query"],
                      "additionalProperties": False}},
    {"name": "find_places", "strict": True,
     "description": "Search Qloo places (cafes, restaurants, shops) by name. Returns [{id, name, type}].",
     "input_schema": {"type": "object", "properties": {"query": _STR}, "required": ["query"],
                      "additionalProperties": False}},
    {"name": "submit_signature", "strict": True,
     "description": "Submit the final taste signature. Call exactly once, as the last step.",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {
         "type": "object", "properties": {
             "id": _STR, "name": _STR, "kind": {"type": "string", "enum": ["tag", "entity"]},
             "weight": {"type": "number"}, "substituted_from": {"type": ["string", "null"]}},
         "required": ["id", "name", "kind", "weight", "substituted_from"], "additionalProperties": False}}},
         "required": ["items"], "additionalProperties": False}},
]


async def build_signature(llm, tools, lto: str, current: list | None = None, instruction: str | None = None):
    seen = {i["id"] for i in current or []}

    async def find_tags(query):
        out = await tools.find_tags(query)
        seen.update(o["id"] for o in out)
        return out

    async def find_places(query):
        out = await tools.find_places(query)
        seen.update(o["id"] for o in out)
        return out

    user = f"LTO: {lto}"
    if current:
        user += f"\n\nCurrent signature: {json.dumps(current)}\nInstruction: {instruction}"

    async for ev in run_tool_loop(llm, system=SIGNATURE_SYSTEM, user=user, tools=SIGNATURE_TOOLS,
                                  handlers={"find_tags": find_tags, "find_places": find_places},
                                  finish_tool="submit_signature"):
        if ev["type"] != "finish":
            yield ev
            continue
        submitted = ev["input"]["items"]
        items = [{**i, "weight": min(1.0, max(0.0, float(i["weight"])))} for i in submitted if i["id"] in seen]
        if not items:
            raise AgentError("no usable Qloo concepts found for this description")
        yield {"type": "signature", "items": items, "dropped": len(submitted) - len(items)}


# --- Scoring run -----------------------------------------------------------------------------

REASONS_SYSTEM = """You explain why each coffee store is a good or bad place to test a new limited-time offer.
For each store, write one sentence of at most 20 words. Cite only tag names from that store's evidence list.
Do not state any taste fact that is not in the evidence."""

REASONS_FORMAT = {"type": "json_schema", "schema": {
    "type": "object", "properties": {"reasons": {"type": "array", "items": {
        "type": "object", "properties": {"store_id": _STR, "reason": _STR},
        "required": ["store_id", "reason"], "additionalProperties": False}}},
    "required": ["reasons"], "additionalProperties": False}}


def _fallback_reason(tags: list[dict]) -> str:
    names = [t["name"] for t in tags[:3]]
    return f"Over-indexes on {', '.join(names)}." if names else "Not enough local taste data."


async def run_score(llm, tools, signature: list[dict]):
    res = await tools.score_stores(signature)
    scored = res["stores"]
    n = sum(s["fit"] is not None for s in scored)
    yield trace("score_stores", {"items": [i["name"] for i in signature]}, f"{n} of {len(scored)} stores scored")

    top, bottom = pick(scored)
    focus = top + bottom
    tastes = await asyncio.gather(*(tools.area_taste(s["id"]) for s in focus))
    evidence = {s["id"]: t["tags"] for s, t in zip(focus, tastes)}
    for s in focus:
        yield trace("area_taste", {"store": s["name"]}, _summarize(evidence[s["id"]]))

    reasons = {sid: _fallback_reason(tags) for sid, tags in evidence.items()}
    payload = [{"store_id": s["id"], "name": s["name"], "fit": s["fit"],
                "evidence": [t["name"] for t in evidence[s["id"]]]} for s in focus]
    try:
        resp = await create(llm, system=REASONS_SYSTEM, output_config={"format": REASONS_FORMAT},
                            messages=[{"role": "user", "content": json.dumps(
                                {"lto_signature": [i["name"] for i in signature], "stores": payload})}])
        for r in json.loads(_text(resp))["reasons"]:
            if r["store_id"] in reasons:
                reasons[r["store_id"]] = r["reason"]
    except (AgentError, json.JSONDecodeError, KeyError):
        pass  # keep the deterministic reasons

    stab = res["stability"]
    names = {i["id"]: i["name"] for i in signature}
    yield {"type": "result", "stores": scored, "top": [s["id"] for s in top], "bottom": [s["id"] for s in bottom],
           "reasons": reasons, "stability": {**stab, "weakest": names.get(stab["weakest"], stab["weakest"])} if stab else None}


# --- Store brief -----------------------------------------------------------------------------

BRIEF_SYSTEM = """You write a short localization brief for one coffee store and a new limited-time offer.
Return a one-sentence verdict (at most 25 words) explaining the fit, and 2-3 short menu cues.
Mention only taste facts from the provided local tags. Do not name any business, artist, or brand."""

BRIEF_FORMAT = {"type": "json_schema", "schema": {
    "type": "object", "properties": {"verdict": _STR, "menu_cues": {"type": "array", "items": _STR}},
    "required": ["verdict", "menu_cues"], "additionalProperties": False}}


def _label(fit: float | None) -> str:
    if fit is None:
        return "maybe"
    return "test" if fit >= 0.5 else "skip" if fit <= -0.5 else "maybe"


async def write_brief(llm, tools, store_id: str, signature: list[dict], fit: float | None) -> dict:
    store = tools.store(store_id)
    taste = await tools.area_taste(store_id)
    label = _label(fit)
    resp = await create(llm, system=BRIEF_SYSTEM, output_config={"format": BRIEF_FORMAT},
                        messages=[{"role": "user", "content": json.dumps({
                            "store": store["name"], "verdict_label": label, "fit_z_score": fit,
                            "lto_signature": [i["name"] for i in signature],
                            "local_tags": [t["name"] for t in taste["tags"]]})}])
    out = json.loads(_text(resp))
    return {"store_id": store_id, "fit": fit, "label": label, "verdict": out["verdict"],
            "why_tags": taste["tags"][:5], "partners": taste["places"][:3], "menu_cues": out["menu_cues"][:3]}
