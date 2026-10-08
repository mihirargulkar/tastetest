import { test } from "node:test";
import assert from "node:assert/strict";
import { foundTags, scoreSteps, signatureSteps, statusText } from "./progress.js";

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

test("statusText names the current step, with detail when present, else Done", () => {
  assert.equal(statusText(scoreSteps([], 40)), "Step 1 of 3: Scoring 40 stores");
  const read = [t("score_stores", "40 of 40 stores scored"), t("area_taste", "3 results: a"), t("area_taste", "3 results: b")];
  assert.equal(statusText(scoreSteps(read.slice(0, 2), 40)), "Step 3 of 3: Writing reasons");
  const mid = [t("score_stores", "40 of 40 stores scored")];
  assert.equal(statusText(scoreSteps(mid, 40)), "Step 2 of 3: Reading each neighborhood");
  assert.equal(statusText([{ label: "A", state: "now", detail: "2 read" }]), "Step 1 of 1: A, 2 read");
  assert.equal(statusText([{ label: "A", state: "done" }, { label: "B", state: "done" }]), "Done");
});
