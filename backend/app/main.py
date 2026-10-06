import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent
from .qloo import Qloo
from .stores import load_stores
from .tools import Tools

ROOT = Path(__file__).resolve().parents[1]  # backend/
DATA = ROOT / "data"
DEMOS = DATA / "demos"
DIST = ROOT.parent / "frontend" / "dist"
LIMITS = {"live": 6, "brief": 30}  # per IP per hour
GLOBAL_LIVE_PER_HOUR = 60  # all clients combined, caps spend if IPs are rotated
GLOBAL_LIVE_PER_DAY = int(os.environ.get("LIVE_RUNS_PER_DAY", "30"))  # all clients combined, rolling 24h
GLOBAL_BRIEFS_PER_HOUR = 300
GLOBAL_BRIEFS_PER_DAY = int(os.environ.get("BRIEFS_PER_DAY", "200"))
LIVE_MODE = os.environ.get("LIVE_MODE", "on").lower() != "off"  # kill switch for paid endpoints
GENERIC_ERROR = "Something went wrong. Try one of the preloaded examples."
log = logging.getLogger(__name__)

app = FastAPI(title="TasteTest")
STORES = load_stores(DATA / "stores.csv")  # loaded at import so /api/stores and demos need no keys


class SignatureItem(BaseModel):
    id: str = Field(max_length=200)
    name: str = Field(max_length=200)
    kind: Literal["tag", "entity"]
    weight: float = Field(ge=0, le=1)
    substituted_from: str | None = Field(default=None, max_length=200)


class SignatureReq(BaseModel):
    lto: str = Field(min_length=1, max_length=500)
    current: list[SignatureItem] | None = Field(default=None, max_length=8)
    instruction: str | None = Field(default=None, max_length=300)


class ScoreReq(BaseModel):
    signature: list[SignatureItem] = Field(min_length=1, max_length=8)


class BriefReq(BaseModel):
    store_id: str = Field(max_length=100)
    signature: list[SignatureItem] = Field(min_length=1, max_length=8)
    fit: float | None = None


def deps(request: Request):
    s = request.app.state
    if not hasattr(s, "tools"):
        rf = DATA / "regions.json"
        cache_dir = Path(os.environ.get("CACHE_DIR", DATA / "cache"))
        s.tools = Tools(Qloo(os.environ["QLOO_API_KEY"], cache_dir), STORES,
                        regions=json.loads(rf.read_text()) if rf.exists() else {})
        s.llm = AsyncAnthropic()
    return s.llm, s.tools


# ponytail: in-memory limiter; resets on restart and assumes a single instance.
# Client = rightmost X-Forwarded-For entry (appended by Render's proxy; earlier entries are client-controlled).
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def check_rate(request: Request, bucket: str) -> None:
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[-1].strip() or (request.client.host if request.client else "unknown")
    glob = GLOBAL_LIVE_PER_HOUR if bucket == "live" else GLOBAL_BRIEFS_PER_HOUR
    now = time.time()
    keys = [((bucket, ip), LIMITS[bucket], 3600), ((bucket, "*"), glob, 3600)]
    if bucket == "live":
        keys.append((("live", "*day"), GLOBAL_LIVE_PER_DAY, 86400))
    else:
        keys.append((("brief", "*day"), GLOBAL_BRIEFS_PER_DAY, 86400))
    for k, limit, window in keys:
        q = _hits[k]
        while q and now - q[0] > window:
            q.popleft()
        if not q:
            del _hits[k]
        if len(q) >= limit:
            raise HTTPException(429, "Live run limit reached for this hour. The preloaded examples still work.")
    for k, _, _ in keys:
        _hits[k].append(now)


def require_live() -> None:
    if not LIVE_MODE:
        raise HTTPException(503, "Live runs are paused. The preloaded examples still work.")


def sse(gen) -> StreamingResponse:
    async def body():
        try:
            async for ev in gen:
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:  # stream boundary: show the failure in the UI instead of a dead stream
            if not isinstance(e, agent.AgentError):
                log.exception("stream failed")
            msg = str(e) if isinstance(e, agent.AgentError) else GENERIC_ERROR
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _items(items: list[SignatureItem] | None) -> list[dict] | None:
    return [i.model_dump() for i in items] if items is not None else None


@app.get("/api/stores")
async def stores():
    return STORES


@app.get("/api/demos")
async def demos():
    out = []
    for p in sorted(DEMOS.glob("*.json")):
        d = json.loads(p.read_text())
        out.append({"slug": d["slug"], "title": d["title"], "lto": d["lto"]})
    return out


@app.get("/api/demos/{slug}")
async def demo(slug: str):
    if slug not in {p.stem for p in DEMOS.glob("*.json")}:
        raise HTTPException(404, "unknown demo")
    return json.loads((DEMOS / f"{slug}.json").read_text())


@app.post("/api/signature")
async def signature(req: SignatureReq, request: Request):
    require_live()
    check_rate(request, "live")
    llm, tools = deps(request)
    return sse(agent.build_signature(llm, tools, req.lto, _items(req.current), req.instruction))


@app.post("/api/score")
async def score(req: ScoreReq, request: Request):
    require_live()
    check_rate(request, "live")
    llm, tools = deps(request)
    return sse(agent.run_score(llm, tools, _items(req.signature)))


@app.post("/api/brief")
async def brief(req: BriefReq, request: Request):
    require_live()
    check_rate(request, "brief")
    llm, tools = deps(request)
    try:
        return await agent.write_brief(llm, tools, req.store_id, _items(req.signature), req.fit)
    except KeyError:
        raise HTTPException(404, "unknown store")
    except agent.AgentError as e:
        raise HTTPException(502, str(e))
    except Exception:
        log.exception("brief failed")
        raise HTTPException(502, GENERIC_ERROR)


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
