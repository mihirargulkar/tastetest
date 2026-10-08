# Live-run loading state: design

**Date:** 2026-10-08
**Status:** approved direction (options A + B from the mockups)

## Goal
A live LTO run takes 10–60 s or more. Today the only feedback is a button label ("Reading the taste…", "Scoring…"). Replace it with a calm, honest loading state that shows the agent's real progress and keeps the map alive. No generic spinners (taste-skill §4.5), and a static fallback under `prefers-reduced-motion` (taste-skill §6.B).

## What drives it
The stream already delivers real progress events, so the UI only renders what has actually happened.

**Signature run** (`/api/signature`): `trace` events with `tool` `find_tags` or `find_places`. The `summary` takes one of these forms:
- `"N results: A, B, C"`
- `"0 results"`
- `"error: Qloo request failed"`

The run ends with a `signature` event.

**Score run** (`/api/score`):
- one `score_stores` trace, after scoring finishes
- `area_taste` traces, one per focus store, arriving as a burst
- a final `result` event

Nothing changes on the backend.

## A. Live work log (`frontend/src/ProgressLog.jsx`, new)
`ProgressLog({ kind, trace })` renders a step checklist.

**Signature steps:**
1. **Reading the drink** is current until the first tag-search trace arrives, then done.
2. **Finding Qloo tags with local data** is current until the run ends.
   - Below it, the names parsed from each successful search summary appear as chips: the text after `": "`, split on `", "`. Show at most 3 per search and at most 12 in total, de-duplicated.
   - Chips pop in as their search arrives.
   - Failed searches add nothing.
3. **Building the taste signature** is the final step and stays current until the stream ends.

**Score steps:**
1. **Scoring {storeCount} stores** is current until the `score_stores` trace arrives.
2. **Reading each neighborhood** is current until the first `area_taste` trace arrives. It then shows `{n} of {m}` while the traces come in.
3. **Writing reasons** is current until the stream ends.

**Visuals:**
- A done step shows a filled green check.
- The current step shows a ring that spins slowly (0.9 s per turn) and label text with a soft shimmer sweep.
- Future steps are muted.

**Placement:**
- During a signature run, `InputCard` renders `ProgressLog` under the "Read the taste" button.
- During a score run, `RankCard` renders `ProgressLog` at the top, above the skeleton.

## B. Skeleton ranking and map scan
- **RankCard while scoring:**
  - a "Test here" label with 5 skeleton rows
  - a "Skip" label with 3 skeleton rows
  - row widths vary, and a shimmer sweeps across them
- **MapView while scoring** (new prop `scanning`):
  - A light vertical band sweeps left to right over the map. It's a CSS overlay `div` with `pointer-events: none`, and the sweep takes 2.2 s.
  - Store dots pulse their radius gently (7↔9 px). This is a `requestAnimationFrame` loop that sets `circle-radius` through `setPaintProperty`. It never touches React state, per taste-skill §5.D.
- **On result:** dots take their colors in sequence, ordered by fit from best to worst, over about 1 s. This works by calling `setData` in batches, roughly every 60 ms. The ranking rows replace the skeleton with a short staggered fade-up.

## Reduced motion
Under `prefers-reduced-motion: reduce`:
- no sweep, pulse, shimmer or stagger
- the spinner becomes a static ring
- the dots recolor at once
- the checklist still updates, because it's information rather than decoration

## Out of scope
- the store-brief loading state ("Building this store's brief…")
- the coffee-cup "pour" (option C)
- any backend change

## Verification
- `npm run build` passes.
- One real live run on the local stack with real keys (a few cents): signature and score.
- Screenshots during each phase.
- One check with reduced motion emulated.
