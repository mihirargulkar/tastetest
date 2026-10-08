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

export function statusText(steps) {
  const i = steps.findIndex((s) => s.state === "now");
  if (i < 0) return "Done";
  const s = steps[i];
  return `Step ${i + 1} of ${steps.length}: ${s.label}${s.detail ? `, ${s.detail}` : ""}`;
}
