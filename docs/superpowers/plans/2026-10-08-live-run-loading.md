# Live-Run Loading State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the text-only loading state of a live LTO run with a live work log (real Qloo progress), skeleton ranking rows, a map scan with pulsing dots, and a staggered color reveal.

**Architecture:**
- Pure helpers in `frontend/src/progress.js` turn the streamed `trace` events into step lists and found-tag chips. They're unit-tested with Node's built-in test runner.
- `ProgressLog.jsx` renders those steps.
- `InputCard`, `RankCard`, `App` and `MapView` wire it in.
- All motion is CSS, plus one `requestAnimationFrame` loop that calls MapLibre `setPaintProperty` directly, never React state.

**Tech Stack:** React, Vite, MapLibre GL 6, plain CSS, `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-08-live-run-loading-design.md`

## Global Constraints
- No backend changes. No new npm dependencies.
- No generic spinners. Skeletons follow the shape of the final layout (taste-skill §4.5).
- Under `prefers-reduced-motion: reduce`:
  - no sweep, pulse, shimmer, stagger or spin
  - the dots recolor at once
  - the checklist still updates
- Animation code never sets React state per frame (taste-skill §5.D).
- Chips: at most 3 names per search, at most 12 in total, de-duplicated. Failed searches add nothing.
- Copy, verbatim:
  - "Reading the drink"
  - "Finding Qloo tags with local data"
  - "Scoring {storeCount} stores"
  - "Reading each neighborhood"
  - "{n} neighborhoods read"
  - "Writing reasons"

---

### Task 1: Pure progress helpers (TDD)

**Files:**
- Create: `frontend/src/progress.js`
- Test: `frontend/src/progress.test.js`

**Interfaces:**
- Produces:
  - `foundTags(trace) -> string[]`
  - `signatureSteps(trace) -> Step[]`
  - `scoreSteps(trace, storeCount) -> Step[]`
  - `Step = { label: string, state: "done" | "now" | "todo", detail?: string }`
- A trace event looks like `{ type: "trace", tool: string, args: object, summary: string }`. Search tools are `find_tags` and `find_places`. A successful summary looks like `"3 results: A, B, C"`. Other summaries are `"0 results"` and `"error: Qloo request failed"`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/progress.test.js`:
```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { foundTags, scoreSteps, signatureSteps } from "./progress.js";

const t = (tool, summary) => ({ type: "trace", tool, args: {}, summary });

test("foundTags parses names, caps 3 per search and 12 total, dedupes, skips failures", () => {
  const trace = [
    t("find_tags", "5 results: Matcha, Matcha Latte, Matcha Ice Cream, Matcha Cake, Matcha Tea"),
    t("find_tags", "0 results"),
    t("find_tags", "error: Qloo request failed"),
    t("find_places", "2 results: Matcha, Cha Cha Matcha"),
    t("score_stores", "40 of 40 stores scored"),
  ];
  assert.deepEqual(foundTags(trace), ["Matcha", "Matcha Latte", "Matcha Ice Cream", "Cha Cha Matcha"]);
  const many = Array.from({ length: 6 }, (_, i) => t("find_tags", `3 results: A${i}, B${i}, C${i}`));
  assert.equal(foundTags(many).length, 12);
});

test("signatureSteps: reading until the first search, then finding", () => {
  assert.deepEqual(signatureSteps([]).map((s) => s.state), ["now", "todo"]);
  assert.deepEqual(signatureSteps([t("find_tags", "1 results: X")]).map((s) => s.state), ["done", "now"]);
  assert.deepEqual(signatureSteps([]).map((s) => s.label), ["Reading the drink", "Finding Qloo tags with local data"]);
});

test("scoreSteps advances on score_stores then area_taste, with a read count", () => {
  assert.deepEqual(scoreSteps([], 40).map((s) => s.state), ["now", "todo", "todo"]);
  assert.equal(scoreSteps([], 40)[0].label, "Scoring 40 stores");
  const scored = [t("score_stores", "40 of 40 stores scored")];
  assert.deepEqual(scoreSteps(scored, 40).map((s) => s.state), ["done", "now", "todo"]);
  const read = [...scored, t("area_taste", "3 results: a"), t("area_taste", "3 results: b")];
  const steps = scoreSteps(read, 40);
  assert.deepEqual(steps.map((s) => s.state), ["done", "done", "now"]);
  assert.equal(steps[1].detail, "2 neighborhoods read");
  assert.equal(steps[2].label, "Writing reasons");
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && node --test src/progress.test.js`
Expected: FAIL with `Cannot find module` for `./progress.js`.

- [ ] **Step 3: Implement `frontend/src/progress.js`**

```js
// Pure helpers: turn streamed trace events into loading-state steps. No React, so node --test can run them.
const SEARCH_TOOLS = new Set(["find_tags", "find_places"]);
const MAX_FOUND = 12;
const PER_SEARCH = 3;

const isSearch = (t) => SEARCH_TOOLS.has(t.tool);

export function foundTags(trace) {
  const out = [];
  for (const t of trace) {
    if (!isSearch(t) || !/^\d+ results: /.test(t.summary || "")) continue;
    const names = t.summary.slice(t.summary.indexOf(": ") + 2).split(", ").slice(0, PER_SEARCH);
    for (const n of names) if (n && !out.includes(n) && out.length < MAX_FOUND) out.push(n);
  }
  return out;
}

function mark(labels, current) {
  return labels.map((label, i) => ({ label, state: i < current ? "done" : i === current ? "now" : "todo" }));
}

export function signatureSteps(trace) {
  // The stream has no "searching finished" marker, so step 2 stays current until the run ends.
  return mark(["Reading the drink", "Finding Qloo tags with local data"], trace.some(isSearch) ? 1 : 0);
}

export function scoreSteps(trace, storeCount) {
  const scored = trace.some((t) => t.tool === "score_stores");
  const reads = trace.filter((t) => t.tool === "area_taste").length;
  const current = !scored ? 0 : reads === 0 ? 1 : 2;
  const steps = mark([`Scoring ${storeCount} stores`, "Reading each neighborhood", "Writing reasons"], current);
  if (reads > 0) steps[1].detail = `${reads} neighborhoods read`;
  return steps;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && node --test src/progress.test.js`
Expected: `# pass 3`, `# fail 0`.

- [ ] **Step 5: Add a test script and commit**

In `frontend/package.json` `"scripts"`, add `"test": "node --test src/"`.

Run: `cd frontend && npm test`. Expected: 3 passing.

```bash
git add frontend/src/progress.js frontend/src/progress.test.js frontend/package.json
git commit -m "feat: pure helpers mapping live-run trace to loading steps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Loading UI (work log, skeleton, map scan, reveal)

**Files:**
- Create: `frontend/src/ProgressLog.jsx`
- Modify:
  - `frontend/src/App.jsx`
  - `frontend/src/InputCard.jsx`
  - `frontend/src/RankCard.jsx`
  - `frontend/src/MapView.jsx`
  - `frontend/src/styles.css`

**Interfaces:**
- Consumes `foundTags`, `signatureSteps` and `scoreSteps` from Task 1.
- Produces:
  - `ProgressLog({ kind: "signature" | "score", trace, storeCount })`
  - a new prop `runTrace` on `InputCard`
  - new props `runTrace` and `storeCount` on `RankCard`
  - a new prop `scanning` on `MapView`

- [ ] **Step 1: Create `frontend/src/ProgressLog.jsx`**

```jsx
import { foundTags, scoreSteps, signatureSteps } from "./progress";

export default function ProgressLog({ kind, trace, storeCount }) {
  const steps = kind === "signature" ? signatureSteps(trace) : scoreSteps(trace, storeCount);
  const tags = kind === "signature" ? foundTags(trace) : [];
  return (
    <ol className="progress" aria-live="polite" aria-label="Run progress">
      {steps.map((s, i) => (
        <li key={s.label} className={`step ${s.state}`}>
          <span className="step-mark" aria-hidden="true">{s.state === "done" ? "✓" : ""}</span>
          <span className="step-body">
            <span className={s.state === "now" ? "step-label shimmer" : "step-label"}>{s.label}</span>
            {s.detail && <span className="step-detail"> · {s.detail}</span>}
            {kind === "signature" && i === 1 && tags.length > 0 && (
              <span className="found">{tags.map((name) => <span key={name} className="chip found-chip">{name}</span>)}</span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
}
```

- [ ] **Step 2: Wire run-scoped trace in `frontend/src/App.jsx`**
  - Add the state `const [runFrom, setRunFrom] = useState(0);` next to the other `useState` calls.
  - In `run(kind, url, body)`, right after `setBusy(kind); setError(null);`, add `setRunFrom(kind === "signature" ? 0 : trace.length);`. A signature run clears the trace, while a score run appends to it.
  - Before `return`, add `const runTrace = trace.slice(runFrom);`.
  - Change the JSX:
    - `<MapView … />` gets `scanning={busy === "score"}`.
    - `<InputCard … />` gets `runTrace={runTrace}`.
    - `<RankCard … />` gets `runTrace={runTrace} storeCount={stores.length}`.

- [ ] **Step 3: `frontend/src/InputCard.jsx`**
  - Add `import ProgressLog from "./ProgressLog";`.
  - Add `runTrace` to the destructured props.
  - Directly after the "Read the taste" `</button>`, insert:
    ```jsx
    {busy === "signature" && <ProgressLog kind="signature" trace={runTrace} />}
    ```

- [ ] **Step 4: `frontend/src/RankCard.jsx`**
  - Add `import ProgressLog from "./ProgressLog";`.
  - Change the signature to `RankCard({ result, busy, onSelect, runTrace, storeCount })`.
  - Replace the whole `if (!result) { … }` block with:
    ```jsx
    if (!result) {
      if (busy) {
        return (
          <section className="card rank-card" aria-busy="true" aria-label="Scoring stores">
            <ProgressLog kind="score" trace={runTrace} storeCount={storeCount} />
            <div className="label">Test here</div>
            {[88, 70, 80, 62, 75].map((w, i) => <div key={i} className="sk" style={{ width: `${w}%` }} />)}
            <div className="label">Skip</div>
            {[66, 78, 58].map((w, i) => <div key={i} className="sk" style={{ width: `${w}%` }} />)}
          </section>
        );
      }
      return (
        <section className="card rank-card">
          <p className="muted">Read the taste, then score stores to see where to test.</p>
        </section>
      );
    }
    ```
  - In `renderRow`, change the signature to `(id, idx)` and the `<li key={id}>` to:
    ```jsx
    <li key={id} className="row-in" style={{ "--i": idx }}>
    ```

- [ ] **Step 5: `frontend/src/MapView.jsx`**
  - Above the component, add:
    ```js
    const RADIUS = ["case", ["get", "selected"], 11, 7];
    const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const greyed = (stores) => stores.map((s) => ({ ...s, fit: null }));
    ```
  - Change the signature to `MapView({ stores, selected, metro, onSelect, scanning })`. In the layer paint, replace the inline `"circle-radius"` expression with `"circle-radius": RADIUS,`.
  - Replace the data effect (`useEffect(() => { if (ready) map.current.getSource("stores").setData(...) }, [ready, stores, selected]);`) with:
    ```js
    const wasScanning = useRef(false);
    useEffect(() => {
      if (!ready) return;
      const src = map.current.getSource("stores");
      const reveal = wasScanning.current && !scanning && stores.some((s) => s.fit != null) && !reduceMotion();
      wasScanning.current = scanning;
      if (!reveal) {
        // While scanning, hide fits so a result that lands a render before busy clears doesn't flash in early.
        src.setData(toGeoJSON(scanning ? greyed(stores) : stores, selected));
        return;
      }
      const order = [...stores].sort((a, b) => (b.fit ?? -99) - (a.fit ?? -99)).map((s) => s.id);
      const batch = Math.ceil(order.length / 16); // about 1 s at 60 ms per batch
      const timers = [];
      let k = 0;
      const step = () => {
        k = Math.min(order.length, k + batch);
        const shown = new Set(order.slice(0, k));
        src.setData(toGeoJSON(stores.map((s) => (shown.has(s.id) ? s : { ...s, fit: null })), selected));
        if (k < order.length) timers.push(setTimeout(step, 60));
      };
      step();
      return () => timers.forEach(clearTimeout);
    }, [ready, stores, selected, scanning]);

    useEffect(() => {
      if (!ready || !scanning || reduceMotion()) return;
      const m = map.current;
      const t0 = performance.now();
      let raf;
      const tick = (now) => {
        m.setPaintProperty("stores", "circle-radius", 8 + Math.sin((now - t0) / 350)); // 7..9 px, no React state
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
      return () => { cancelAnimationFrame(raf); m.setPaintProperty("stores", "circle-radius", RADIUS); };
    }, [ready, scanning]);
    ```
  - Change the returned element to include the overlay:
    ```jsx
    return (
      <div ref={container} className="map" role="region" aria-label="Map of stores colored by fit">
        {scanning && !reduceMotion() && <div className="map-scan" aria-hidden="true" />}
      </div>
    );
    ```

- [ ] **Step 6: Append to `frontend/src/styles.css`**

```css
/* Live-run loading state */
.progress { list-style: none; margin: 12px 0 4px; padding: 0; }
.step { display: flex; gap: 8px; align-items: flex-start; padding: 4px 0; color: var(--muted); font-size: 13px; }
.step.done, .step.now { color: var(--ink); }
.step-mark { width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--line); flex: none; margin-top: 2px; display: grid; place-items: center; font-size: 9px; color: #fff; }
.step.done .step-mark { background: var(--green-dark); border-color: var(--green-dark); }
.step.now .step-mark { border-color: var(--green-dark); border-top-color: transparent; }
.step-detail { color: var(--muted); }
.found { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.found-chip { padding: 2px 9px; }
.sk { height: 10px; border-radius: 5px; background: #eee9df; margin: 9px 0; }
.map-scan { position: absolute; inset: 0; z-index: 1; pointer-events: none; overflow: hidden; }
.map-scan::before { content: ""; position: absolute; top: 0; bottom: 0; width: 140px; left: -140px;
  background: linear-gradient(90deg, transparent, rgba(255, 253, 248, 0.45), transparent); }
@media (prefers-reduced-motion: no-preference) {
  .step.now .step-mark { animation: tt-spin 0.9s linear infinite; }
  .shimmer { background: linear-gradient(90deg, var(--ink) 40%, #b9b2a4 50%, var(--ink) 60%); background-size: 250% 100%;
    -webkit-background-clip: text; background-clip: text; color: transparent; animation: tt-shimmer 1.8s linear infinite; }
  .found-chip { animation: tt-pop 0.35s ease-out both; }
  .sk { background: linear-gradient(90deg, #eee9df 25%, #f8f5ef 50%, #eee9df 75%); background-size: 200% 100%;
    animation: tt-sk 1.3s ease-in-out infinite; }
  .map-scan::before { animation: tt-scan 2.2s ease-in-out infinite; }
  .row-in { animation: tt-pop 0.35s ease-out both; animation-delay: calc(var(--i) * 70ms); }
}
@keyframes tt-spin { to { transform: rotate(360deg); } }
@keyframes tt-shimmer { from { background-position: 100% 0; } to { background-position: -150% 0; } }
@keyframes tt-pop { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@keyframes tt-sk { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@keyframes tt-scan { from { left: -140px; } to { left: 100%; } }
```

- [ ] **Step 7: Verify the build and unit tests**

Run: `cd frontend && npm test && npm run build`
Expected: 3 tests pass, and `✓ built`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/ProgressLog.jsx frontend/src/App.jsx frontend/src/InputCard.jsx frontend/src/RankCard.jsx frontend/src/MapView.jsx frontend/src/styles.css
git commit -m "feat: live-run loading state (work log, skeleton ranking, map scan, color reveal)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Visual verification (the controller does this in the browser pane)**

1. Start the local stack with real keys.
2. Run one live signature and one live score.
3. Screenshot each phase.
4. Emulate reduced motion and confirm nothing animates.

---

## Self-review
- **Spec coverage:**
  - Work log steps and chips: Task 1 and Task 2 Steps 1–3.
  - Score log and skeleton: Step 4.
  - Map scan, pulse and staggered reveal: Step 5.
  - Reduced motion: CSS gating, plus the `reduceMotion()` checks in Step 5.
  - Placement: Steps 3–4.
  - Verification: Step 9.
- **Names line up across tasks:** `foundTags`, `signatureSteps`, `scoreSteps`, `runTrace`, `storeCount` and `scanning` are used the same way in both tasks.
- **Out of scope, as the spec says:** the store-brief loading state, option C, and any backend change.
