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
