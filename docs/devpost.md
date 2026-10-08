# Devpost submission: TasteTest

## Project name
TasteTest

## Tagline (elevator pitch)
Tells a coffee chain which stores to test a new drink in, and why, from local demand for the drink's ingredients in Qloo's taste data.

## Links ("Try it out")
- Live demo: https://tastetest-i5p5.onrender.com/ (the tool itself is at `/app/`)
- Code: https://github.com/mihirargulkar/tastetest (MIT)

## Built with
python, fastapi, react, vite, maplibre-gl, claude, anthropic-api, qloo-api, docker, render, openfreemap, openstreetmap

---

## About the project

### Inspiration
Specialty coffee chains with 15 to 70 stores launch limited-time drinks several times a year, and every launch starts with the same question: which stores should test it first? These chains are too big for the founder to know every neighborhood, and too small to have a data team. So test stores get picked by gut feel, and a good drink can die in the wrong neighborhood.

An LLM can't fix this alone. Ask one which Bay Area neighborhoods want a matcha-yuzu cold brew and it will guess with confidence. I wanted a version that only works because it has Qloo's location-level taste data behind it.

### What it does
1. **Describe the drink in plain words**, e.g. "Matcha-yuzu cold brew: bright, citrusy, aimed at a younger crowd."
2. **A Claude agent builds a taste signature.** It searches Qloo for real dish and drink tags (`/v2/tags`, `/search`) and keeps only tags that have heatmap data in the chain's regions. When a word has no match, it substitutes the closest concept and says so on screen ("yuzu → Yuzu Sorbet"). Any ID that Qloo didn't return is thrown away, and names always come from Qloo, never from the model.
3. **Every store gets a score** from Qloo heatmaps. The demo covers 40 Philz Coffee stores in two regions, the Bay Area and the LA basin. The map shows where to test and where to skip, with a one-line reason per store.
4. **Click any store for a brief:**
   - a verdict
   - which signature items drive its score versus the chain average
   - the area's Qloo taste tags
   - nearby collab partners: bakeries, dessert shops, tea houses, bookstores and ice cream shops that Qloo returned
5. **A stability check tells you how much to trust a ranking.** The ranking is recomputed with each concept left out. The worst-case Spearman ρ is shown, so you can see whether a result hangs on a single tag.

Three demo drinks are precomputed, so judges can explore instantly with no wait and no live API cost. You can also type your own drink and watch the agent trace stream every Qloo call.

### How it's Qloo-powered
Qloo provides the signal at every step:
- **Tag search** grounds the drink in Qloo's vocabulary.
- **Heatmaps** (`filter.type=urn:heatmap`, with a WKT polygon per region) give location-level affinity. Each store takes the nearest heatmap cell within 1.5 km, combined as a weighted mean across the signature and z-scored across the chain.
- **Location-filtered place insights** supply each neighborhood's taste tags and its collab partners.

Without Qloo there is nothing to rank. The LLM only chooses concepts and writes prose; every score comes from deterministic code over Qloo data.

**The math.** Each signature item $i$ has a weight $w_i$. For store $s$, let $a_{s,i}$ be the affinity of the nearest Qloo heatmap cell within 1.5 km, and let $I_s$ be the items that have such a cell. An item with no nearby data is skipped, not counted as zero. The store's affinity and its fit are:

$$A_s = \frac{\sum_{i \in I_s} w_i \, a_{s,i}}{\sum_{i \in I_s} w_i}, \qquad \text{fit}_s = \frac{A_s - \bar{A}}{\sigma_A}$$

The stability check drops one item $j$ at a time, re-scores every store, and reports the worst-case rank agreement with the full ranking:

$$\rho_{\min} = \min_{j} \; \rho_{\text{Spearman}}\left(\text{fit}, \; \text{fit}^{(-j)}\right)$$

### How I built it
- **Backend:** Python and FastAPI.
  - A hand-written Claude tool-use loop: 12 tool calls max, with Qloo tag search and place search as tools.
  - Pure scoring math with 67 tests, behind a small Qloo client with disk caching and 429 back-off.
  - Responses stream to the browser over server-sent events.
- **Frontend:** React, Vite and MapLibre on free OpenFreeMap tiles. The landing page and the tool are separate pages in the same build.
- **Deployment:** one Docker service on Render.
- **Spend controls** for a public demo:
  - per-IP and global hourly limits, plus daily caps
  - a `LIVE_MODE` kill switch
  - a 60-second model timeout
  - precomputed demos that need no API keys

### Challenges I ran into
- **Most tags have no heatmap data.** Probing the hackathon API showed heatmaps only return data for `specialty_dish` tags and place entities. So the agent became coverage-aware: it sees each tag's cell count and only keeps tags that have data.
- **Coverage varies a lot by city.** Philadelphia returned zero heatmap cells, which ruled out Philly-heavy chains. Per-city queries were sparse too (Palo Alto had 21 cells), so I switched to region polygons. The Bay Area box returns 267 matcha cells and covers 30 of Philz's stores.
- **The score was measuring popularity, not taste.** In my first version, three unrelated drinks produced nearly the same ranking (fit correlations up to 0.90). I tested five scoring variants against the data and found that, in this API, heatmap affinity for most dish tags tracks local popularity ($r \approx 0.91$ to $0.95$). Treating "no nearby data" as missing rather than zero brought the cross-drink correlations down to 0.48 to 0.67. Rather than overclaim, the app labels the score honestly as *local demand for the drink's ingredients* and shows the per-item drivers behind every store.
- **Engineering details:**
  - MapLibre's web worker broke under Vite's bundling, so the map rendered blank; I loaded the worker explicitly instead.
  - Qloo rate-limits bursts, so concurrency is capped at 3 with exponential back-off.

### Accomplishments I'm proud of
- Every name on screen is traceable to a Qloo response, and the model can't invent a tag, a store or a partner.
- The stability check stays high across the demos (ρ of 0.90, 0.88 and 0.75), and it's visible to the user.
- I measured a real limitation in the data and designed the product around it instead of hiding it.

### What I learned
Grounding an agent means more than giving it an API. You have to check what the data actually says. The most valuable work in this project was probing the API, finding where the signal was weak, and making the product honest about it.

### What's next
- Test Qloo audience and demographic signals as a more taste-specific input than heatmaps.
- Add item coverage to the confidence score.
- Let a chain upload its own store list and draw its own regions.
- Close the loop by importing real LTO sales results to calibrate the ranking.

*TasteTest is a prioritization tool for choosing test stores, not a sales forecast. Not affiliated with Philz Coffee.*
