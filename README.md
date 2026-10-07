# TasteTest

**Tells a coffee chain which stores to test a new drink in, and why, based on local demand for the drink's ingredients.**

Live demo: <Render URL> · Built for the [Qloo Agentic Hackathon](https://qloo.devpost.com)

## What it does

1. Describe a limited-time offer in plain language ("matcha-yuzu cold brew, bright and citrusy, for a younger crowd").
2. A Claude agent turns it into a **taste signature**: real Qloo specialty-dish tags found with `/v2/tags` and `/search`. It picks only tags that have heatmap data in the chain's regions. When a word has no Qloo match, the agent substitutes the closest concept and shows the substitution. Any ID a search didn't return is discarded.
3. Every store is scored from **Qloo heatmaps**. Stores are scored in two region polygons (Bay Area, LA basin) by the nearest heatmap cell within 1.5 km. An item with no nearby cell is skipped, not zeroed. The result is a weighted mean across items, z-scored across the chain.
4. The map shows **where to test and where to skip**, with one-line reasons that cite only Qloo data for each area.
5. **Stability check:** leave-one-out Spearman ρ. The ranking is recomputed with each item left out, and the worst case is shown, so you can see whether the result hangs on a single tag.
6. Click any store for a **store brief**: a verdict, "what drives this score" per-item drivers, local taste tags, and local collab partners (nearby bakeries, dessert shops, tea houses, bookstores and ice cream shops from Qloo).

**Honest note:** in this API, heatmap affinity largely tracks local popularity, so the score is presented as *local demand for the drink's ingredients*, not pure taste.

Scores come from deterministic code; the LLM only picks concepts and writes prose. It's a prioritization tool for choosing test stores, not a sales forecast. Not affiliated with Philz Coffee.

## Run locally

```bash
cd backend && python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export QLOO_API_KEY=...  ANTHROPIC_API_KEY=...
uvicorn app.main:app --port 8000
# second terminal
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Tests: `cd backend && pytest`

## Spend controls

Live runs call paid APIs, so they are capped:

- `LIVE_MODE=off` disables all paid endpoints (kill switch).
- `LIVE_RUNS_PER_DAY` (default 30) caps live agent runs across all clients per rolling 24h.
- `BRIEFS_PER_DAY` (default 200) caps live store briefs.

The preloaded demos and their briefs are served from precomputed files and need no keys.

## Use your own chain

1. Replace `backend/data/stores.csv` with your stores; `scripts/geocode.py` fills in lat/lon.
2. Edit `backend/data/regions.json` with a polygon per metro your stores sit in.
3. Run `scripts/coverage_check.py` to confirm Qloo has heatmap data for your regions.
4. Set `CHAIN` in `frontend/src/config.js`.
5. Re-run `scripts/precompute_demos.py`.

## License

MIT
