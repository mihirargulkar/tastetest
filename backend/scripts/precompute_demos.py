"""Run the full pipeline for the preloaded examples and save results, so judges get instant, outage-proof demos.

Usage: QLOO_API_KEY=... ANTHROPIC_API_KEY=... python scripts/precompute_demos.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anthropic import AsyncAnthropic  # noqa: E402

from app import agent  # noqa: E402
from app.qloo import Qloo  # noqa: E402
from app.stores import load_stores  # noqa: E402
from app.tools import Tools  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"
DEMOS = [
    ("matcha-yuzu", "Matcha-yuzu cold brew", "Matcha-yuzu cold brew: bright, citrusy, aimed at a younger crowd"),
    ("maple-oat", "Brown-butter maple oat latte", "Brown-butter maple oat latte: cozy, nostalgic, fall comfort"),
    ("smoky-tonic", "Smoky cold brew tonic", "Smoky cold brew tonic: cold brew over tonic with a smoked-citrus finish, bold and adventurous for the after-work crowd"),
]


async def run_one(llm, tools, slug, title, lto):
    trace, signature, result = [], None, None
    async for ev in agent.build_signature(llm, tools, lto):
        if ev["type"] == "trace":
            trace.append(ev)
        else:
            signature = ev["items"]
    async for ev in agent.run_score(llm, tools, signature):
        if ev["type"] == "trace":
            trace.append(ev)
        else:
            result = ev
    fits = {s["id"]: s["fit"] for s in result["stores"]}
    ids = result["top"] + result["bottom"]
    briefs = await asyncio.gather(*(agent.write_brief(llm, tools, i, signature, fits[i]) for i in ids))
    out = {"slug": slug, "title": title, "lto": lto, "signature": signature, "result": result,
           "briefs": dict(zip(ids, briefs)), "trace": trace}
    (DATA / "demos" / f"{slug}.json").write_text(json.dumps(out, indent=1))
    print(f"{slug}: {len(signature)} concepts, top={result['top'][:3]}, stability={result['stability']}", flush=True)


async def main():
    rf = DATA / "regions.json"
    tools = Tools(Qloo(os.environ["QLOO_API_KEY"], DATA / "cache"), load_stores(DATA / "stores.csv"),
                  regions=json.loads(rf.read_text()) if rf.exists() else {})
    llm = AsyncAnthropic()
    for d in DEMOS:
        await run_one(llm, tools, *d)


if __name__ == "__main__":
    asyncio.run(main())
