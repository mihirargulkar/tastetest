# LTO Rollout Planner — Design

**Working name:** TasteTest
**Hackathon:** Qloo Agentic Hackathon (https://qloo.devpost.com) — deadline **Oct 30, 2026, 11:45pm EDT**
**Date:** 2026-10-02

## 1. Problem and pitch

Mid-size specialty coffee chains (15–70 stores, multiple metros) launch limited-time offers (LTOs) several times a year. They are too big for the founder to know every neighborhood and too small to have a data science team or pay for market research. Picking the wrong test stores wastes the test budget and can kill a good product.

TasteTest is an agent that takes a plain-language LTO description and tells the chain **which stores to test it in, which to skip, and why**, using Qloo's location-scoped taste data. For any store, it also produces a localization brief (verdict, evidence, local collab partners, menu cues).

**Why it needs Qloo:** the output is a per-store ranking derived from neighborhood-level affinity data. An LLM alone can only guess what Williamsburg likes; it cannot produce comparable scores across 30 addresses.

**What we do not claim:** sales prediction. TasteTest is a prioritization tool for choosing test stores, and the UI says so.

## 2. Target chain

**Philz Coffee**, using its **public store addresses**. A live probe on 2026-10-06 found the hackathon API has no heatmap data for Philadelphia (0 cells) and very little for Boston and Brooklyn. That rules out La Colombe and Joe Coffee. The San Francisco Bay Area is the best-covered region (156 cells for matcha in SF). `coverage_check.py` (§7) counts heatmap cells for each of Philz's metros, and metros with too little data are left out of the demo.

Brand guardrails: name the chain only as a description ("analysis of [Chain]'s stores"), no logo, colors, or trade dress, and a visible "not affiliated with [Chain]" note. Store data lives in `stores.csv` (`name, address, lat, lon, metro`), so swapping chains means replacing one file.

## 3. Scoring model (deterministic code, not the LLM)

1. **Taste signature.** The LTO becomes 3–8 weighted Qloo IDs (built by the agent, §4, and editable by the user). Only two kinds of ID are allowed, because they're the only ones the hackathon API returns heatmaps for: **`urn:tag:specialty_dish:place:*` tags** (dishes, drinks, ingredients, e.g. matcha latte) and **place entity IDs** (e.g. a well-known matcha café).
2. **Fit score.** One Qloo **heatmap** request per metro per signature item (`filter.location.query` = metro). Heatmap cells are sparse points, about 0.2–0.8 km apart, and only appear where there's signal. Affinity is rank-normalized 0–1 within each city. For each item, a store takes the affinity of the nearest cell within 1.5 km. If the city has cells for that item but none near the store, the store gets affinity 0, since no signal nearby means low interest. If the city has no cells for that item, the item is skipped for that store. Store affinity is the weighted mean across items. Fit is the z-score of store affinity across all stores in the chain. Because affinity is a within-city rank, fit means "how this neighborhood ranks within its own city, compared with the chain's other stores". The UI says "relative to each city".
3. **Confidence.** The mean Qloo popularity of the cells used. Below 0.2, the store is marked low-confidence (faded on the map and in the list). A store with no usable items shows "no data".
4. **Stability check (leave-one-out).** For each signature item, re-score with that item removed and compute the Spearman rank correlation (ρ) between the full ranking and the reduced one. Report the minimum ρ and the item whose removal moves the ranking most ("Ranking holds when any single concept is dropped: ρ ≥ 0.86; most sensitive to *matcha latte*"). This uses heatmaps already fetched, so it costs no extra Qloo calls. It answers whether the ranking hangs on one shaky tag. It isn't proof of sales. With fewer than 2 items, no check is shown.

*Rejected after probing:* counting nearby related places. `filter.tags` with specialty-dish tags returns 0 places everywhere. Category tags return 0–2 tea houses, and café counts measure café density, not interest in the drink.

Rate limits: the hackathon API returns 429 under bursty load. At most 3 Qloo requests run at once, with exponential back-off on 429.

## 4. Agent loop

Claude Sonnet 5.5 (`claude-sonnet-5-5`) with standard tool use and a hand-written loop. No agent framework.

**Tools:**

| Tool | Wraps | Purpose |
|---|---|---|
| `find_tags(query)` | `GET /v2/tags`, filtered to `specialty_dish:place` tags | Resolve a dish/drink/ingredient concept to a Qloo tag ID |
| `find_entities(query)` | `GET /search` (`types=urn:entity:place`) | Anchor place entities (e.g. a well-known matcha café) |
| `score_stores(signature)` | heatmap per metro per item + §3 code | Ranked stores with fit, confidence and stability |
| `area_taste(store_id)` | `urn:tag` with `signal.location`, plus `urn:entity:place` with `filter.location` | Top area tags and nearby places for a store |

**Run sequence:**
1. Break the LTO into dish, drink and ingredient concepts and resolve each with `find_tags` / `find_entities`. On an empty result, retry with a broader or synonymous term (e.g. "yuzu" → "citrus") and record the substitution.
2. Show the signature as editable chips, with substitutions labeled. Wait for the user to confirm.
3. Call `score_stores`. Neither the agent nor the user can change the scores.
4. For the top 5 and bottom 3 stores, gather `area_taste` evidence in code. Claude writes the one-line reasons in one structured call, citing only returned tags. Deterministic "Over-indexes on …" reasons are used if that call fails.
5. On store click, call `area_taste` and write the brief. It may only name places Qloo returned. No playlist: location-based artist results are dominated by megastars and include unsafe raw entries.

**Follow-ups:** a chat box ("re-run for an older crowd", "drop yuzu") edits the signature and re-scores.

**Limits:** max 25 tool calls per run. If hit, show the partial results with a note.

## 5. UI

A single screen, map-first (mockup "B"):

- **Full-bleed MapLibre map.** Stores are dots colored by fit z-score on a diverging green↔red scale. Low-confidence stores are faded.
- **Floating input card (top-left).** LTO textarea, signature chips (editable, substitutions labeled, e.g. "yuzu → citrus"), and a "Score stores" button.
- **Floating ranking card (top-right).** "Test here" (top 5) and "Skip" (bottom 3), each with fit score and a one-line reason.
- **Bottom bar.** A collapsible agent trace (each tool call with a short result summary, streamed live) and the stability line (§3.4).
- **Store drawer** (opens on clicking a dot or list row):
  1. Store name and fit score, then a **verdict line** ("✅ Test here. The neighborhood leans hard into Japanese café culture.")
  2. Fit meter vs. chain average (relative to each city), plus confidence
  3. Why it fits: over-indexed Qloo tags (source + radius shown)
  4. Local collab partners: nearby Qloo places
  5. Menu cues

  It is one scroll, with no tabs.
- **"Not affiliated with [Chain]"** note and a "prioritization, not sales prediction" note in the footer.

Not included: login, dashboard home page, settings, charts that duplicate the list.

**Landing page:** built in Framer on its own domain. Hero text, a globe or multi-location map component showing the chain's cities, and a "Try it" button linking to the app.

## 6. Architecture and hosting

- **Backend:** Python, FastAPI. The agent loop uses the Anthropic SDK; Qloo calls use `httpx` against `https://hackathon.api.qloo.com` with the `X-Api-Key` header. The agent trace streams to the browser over SSE.
- **Frontend:** React (Vite) + MapLibre, built to static files and served by FastAPI. One origin.
- **Hosting:** one Render or Fly service. `QLOO_API_KEY` and `ANTHROPIC_API_KEY` are server-side environment variables only.
- **Repo:** public, with an MIT `LICENSE` that shows in GitHub's About section, plus a README with run instructions.

## 7. Reliability and testing

- **Precomputed demo runs:** 3 LTOs, full results saved as JSON in the repo and served instantly. This is the primary safeguard for judging.
- **Qloo response cache:** on disk, keyed by request params.
- **Qloo rate limits:** at most 3 concurrent requests, retry on 429 with exponential back-off (honor `Retry-After` when present).
- **Empty or error responses** are returned to the agent as data so it can retry with another term.
- **Rate limit** on the live scoring endpoint (per-IP, a few runs per hour).
- **If Qloo or Anthropic is down:** demo runs still work. Live runs show a banner instead of a blank screen.
- `test_scoring.py`: fake heatmap in, expected z-scores, confidence flags and stability ρ out.
- `coverage_check.py`: for each Philz metro, counts heatmap cells for reference tags (matcha, coffee) and how many stores have a cell within 1.5 km. Metros below 10 cells are dropped (§2).
- No frontend tests. Manual browser check before submission.

## 8. Submission checklist

- [ ] Live hosted app URL (works with no login)
- [ ] Public repo + MIT license visible in About
- [ ] Text description: what the agent does and what makes it Qloo-powered
- [ ] Framer landing page (optional, if time allows)

## 9. First actions

1. ~~Request the Qloo hackathon API key~~ Done; the key is in `.env` (gitignored).
2. ~~Confirm the §3 parameters against the live API~~ Done 2026-10-06 (findings folded into §2–§4).
3. Collect Philz store addresses and run `coverage_check.py` to choose which metros to include.
