// The camera lights up what she names, as she says it (same rules as the Stage in Kairos).
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(new URL("../src/inject/cues.js", import.meta.url), "utf8"), sandbox);
const { mentions, focusAt } = sandbox.window.__jennyCues;

const cities = [
  { key: "Chennai", label: "Chennai", aliases: ["Chennai"] },
  { key: "Delhi", label: "Delhi", aliases: ["Delhi"] },
  { key: "Noida-1", label: "Noida-1", aliases: ["Noida-1", "Noida"] },
];

test("names are found in the order she says them", () => {
  assert.deepEqual([...mentions("Chennai and Delhi are up; Noida looks extreme.", cities).map((m) => m.key)], ["Chennai", "Delhi", "Noida-1"]);
});

test("only what she has said so far is lit", () => {
  const line = "Chennai is up the most, and Delhi is close behind.";
  assert.deepEqual([...focusAt(line, 0.1, cities)], ["Chennai"]);
  assert.deepEqual([...focusAt(line, 0.95, cities)], ["Chennai", "Delhi"]);
  assert.equal(focusAt("Cancellations are a little high.", 0.5, cities), null);
});
