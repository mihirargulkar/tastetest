# LTO Rollout Planner — Design

**Working name:** TasteTest
**Hackathon:** Qloo Agentic Hackathon (https://qloo.devpost.com) — deadline **Oct 30, 2026, 11:45pm EDT**
**Date:** 2026-10-02

## 1. Problem and pitch

Mid-size specialty coffee chains (15–70 stores, multiple metros) launch limited-time offers (LTOs) several times a year. They are too big for the founder to know every neighborhood and too small to have a data science team or pay for market research. Picking the wrong test stores wastes the test budget and can kill a good product.

TasteTest is an agent that takes a plain-language LTO description and tells the chain **which stores to test it in, which to skip, and why**, using Qloo's location-scoped taste data. For any store, it also produces a localization brief (verdict, evidence, playlist seed, local collab partners, menu cues).

**Why it needs Qloo:** the output is a per-store ranking derived from neighborhood-level affinity data. An LLM alone can only guess what Williamsburg likes; it cannot produce comparable scores across 30 addresses.

**What we do not claim:** sales prediction. TasteTest is a prioritization tool for choosing test stores, and the UI says so.

## 2. Target chain

A real mid-size, multi-city specialty coffee chain, using its **public store addresses**. Shortlist: Philz, La Colombe, Joe Coffee. The final pick is made by `coverage_check.py` (§7) once the Qloo key arrives: the chain whose stores show the most varied Qloo taste profiles wins.

Brand guardrails: name the chain only as a description ("analysis of [Chain]'s stores"), no logo, colors, or trade dress, and a visible "not affiliated with [Chain]" note. Store data lives in `stores.csv` (`name, address, lat, lon, metro`), so swapping chains means replacing one file.

## 3. Scoring model (deterministic code, not the LLM)

1. **Taste signature.** The LTO becomes 3–8 weighted Qloo tag/entity IDs (built by the agent, §4, and editable by the user).
2. **Fit score.** For each metro, one Qloo **heatmap** request with the signature as the signal. Each store gets the affinity of the heatmap cell containing its coordinates. Fit = z-score of that affinity against all stores in the chain. Positive means the neighborhood over-indexes, negative means it under-indexes.
3. **Confidence.** Taken from the cell's Qloo popularity value. Below a threshold, the store is marked low-confidence (shown faded on the map and in the list).
4. **Validation signal.** For each store, count nearby Qloo places matching the signature's tags (e.g. tea/matcha spots near the café). Show the ratio of that count between the top-ranked and bottom-ranked stores ("top stores have 2.3× more nearby matcha/tea spots"). This is an independent check on the ranking, not proof of sales.

**Fallback** if heatmap parameters don't behave as documented: a location-scoped `/v2/insights` call per store with the signature as `signal.interests.*`. Same z-score, more calls.

To confirm against the live API on day 1: heatmap request shape and cell resolution, the popularity field used for confidence, taste-analysis parameters for area tags.

## 4. Agent loop

Claude Sonnet 5.5 (`claude-sonnet-5-5`) with standard tool use and a hand-written loop. No agent framework.

**Tools:**

| Tool | Wraps | Purpose |
|---|---|---|
| `find_tags(query)` | `GET /v2/tags` | Resolve a concept to a Qloo tag ID |
| `find_entities(query, type)` | `GET /search` | Anchor entities (brands, places) |
| `score_stores(signature)` | heatmap per metro + §3 code | Ranked stores with fit and confidence |
| `area_taste(store_id)` | location-scoped insights / taste analysis | Top tags, artists, places, brands near a store |
| `nearby_related(store_id, tag)` | location-scoped place search | Validation count (§3.4) |

**Run sequence:**
1. Break the LTO into concepts and resolve each with `find_tags` / `find_entities`. On an empty result, retry with a broader or synonymous term (e.g. "yuzu" → "citrus") and record the substitution.
2. Show the signature as editable chips, with substitutions labeled. Wait for the user to confirm.
3. Call `score_stores`. The agent may annotate low-confidence stores but cannot change scores.
4. For the top 5 and bottom 3 stores, call `area_taste` and `nearby_related` and write one-line reasons that cite only returned tags.
5. On store click, call `area_taste` (artists, places, brands) and write the brief. It may only name entities Qloo returned.

**Follow-ups:** a chat box ("re-run for an older crowd", "drop yuzu") edits the signature and re-scores.

**Limits:** max 25 tool calls per run. If hit, show the partial results with a note.

## 5. UI

A single screen, map-first (mockup "B"):

- **Full-bleed MapLibre map.** Stores are dots colored by fit z-score on a diverging green↔red scale. Low-confidence stores are faded.
- **Floating input card (top-left).** LTO textarea, signature chips (editable, substitutions labeled, e.g. "yuzu → citrus"), and a "Score stores" button.
- **Floating ranking card (top-right).** "Test here" (top 5) and "Skip" (bottom 3), each with fit score and a one-line reason.
- **Bottom bar.** A collapsible agent trace (each Qloo call with a short result summary, streamed live) and the validation line.
- **Store drawer** (opens on clicking a dot or list row):
  1. Store name and fit score, then a **verdict line** ("✅ Test here. The neighborhood leans hard into Japanese café culture.")
  2. Fit meter vs. chain average, plus confidence
  3. Why it fits: over-indexed Qloo tags (source + radius shown)
  4. Playlist seed: Qloo artists with affinity scores
  5. Local collab partners: Qloo places/brands
  6. Menu cues

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
- **Empty or error responses** are returned to the agent as data so it can retry with another term.
- **Rate limit** on the live scoring endpoint (per-IP, a few runs per hour).
- **If Qloo or Anthropic is down:** demo runs still work. Live runs show a banner instead of a blank screen.
- `test_scoring.py`: fake heatmap in, expected z-scores and confidence flags out.
- `coverage_check.py`: queries 10 neighborhoods for each shortlisted chain and prints the variance of their taste profiles (§2).
- No frontend tests. Manual browser check before submission.

## 8. Submission checklist

- [ ] Live hosted app URL (works with no login)
- [ ] Public repo + MIT license visible in About
- [ ] Text description: what the agent does and what makes it Qloo-powered
- [ ] Framer landing page (optional, if time allows)

## 9. First actions

1. Request the Qloo hackathon API key today (it takes a few business days).
2. Once the key arrives: confirm the §3 parameters against the live API, then run `coverage_check.py` and pick the chain.
