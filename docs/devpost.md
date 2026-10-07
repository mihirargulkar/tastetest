**TasteTest tells a coffee chain which stores to test a new drink in, and why, based on local demand for the drink's ingredients.**

Mid-size specialty coffee chains launch limited-time drinks several times a year. With dozens of stores across several cities, they're too big to know every neighborhood and too small for a data team, so new drinks often get tested in the wrong stores.

**How it's Qloo-powered:** A Claude agent turns a plain-language drink description into a taste signature of real Qloo specialty-dish tags (`/v2/tags`, `/search`), choosing only tags with heatmap data in the chain's regions. Each store is scored from Qloo heatmaps by the nearest cell within 1.5 km, as a weighted mean z-scored across the chain. A leave-one-out Spearman ρ stability check shows whether the ranking hangs on any single item. Honestly, heatmap affinity largely tracks local popularity, so we frame the score as local demand, not pure taste. Store briefs give a verdict, per-item drivers, local taste tags, and local collab partners (nearby bakeries, dessert shops, tea houses) that Qloo returned. Without Qloo, there is nothing to rank: an LLM can only guess.

**Try it:** open the demo, pick a preloaded drink, click any store. Or type your own drink. The agent trace shows every Qloo call.

Built with FastAPI, Claude (tool use), React, and MapLibre. MIT licensed. Not affiliated with Philz Coffee.
