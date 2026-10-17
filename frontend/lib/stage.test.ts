import { describe, expect, it } from "vitest";

import { focusAt, mentions, stage, type Scene } from "./stage";

const cities = [
  { key: "Chennai", label: "Chennai", aliases: ["Chennai"] },
  { key: "Delhi", label: "Delhi", aliases: ["Delhi"] },
  { key: "Noida-1", label: "Noida-1", aliases: ["Noida-1", "Noida"] },
  { key: "Pune", label: "Pune", aliases: ["Pune"] },
];
const hours = [
  { key: "h9", label: "9 am", aliases: ["9 am", "9am", "9 a.m.", "nine am", "nine a.m.", "09:00", "9:00", "nine o'clock"] },
  { key: "h19", label: "7 pm", aliases: ["7 pm", "seven p.m."] },
];

describe("linking her words to the stage", () => {
  it("finds every name she says, in the order she says them", () => {
    expect(mentions("[thoughtful] Chennai and Delhi are driving it; Noida looks extreme.", cities).map((m) => m.key)).toEqual([
      "Chennai",
      "Delhi",
      "Noida-1",
    ]);
  });

  it("matches whole words only", () => {
    expect(mentions("The Punekar outlet is fine.", cities)).toEqual([]);
    expect(mentions("At nine a.m. it dipped.", hours).map((m) => m.key)).toEqual(["h9"]);
    expect(mentions("At 19:00 it dipped.", hours)).toEqual([]);
  });

  it("lights up only what she has said so far in the line", () => {
    const line = "Chennai is up the most, and Delhi is close behind.";
    expect(focusAt(line, 0.1, cities)).toEqual(["Chennai"]);
    expect(focusAt(line, 0.9, cities)).toEqual(["Chennai", "Delhi"]);
    expect(focusAt("Cancellations are a little high overall.", 0.5, cities)).toBeNull();
  });
});

describe("the shared stage", () => {
  const scene = (id: string, focus: string[] = []): Scene => ({
    id,
    kind: "breakdown",
    title: id,
    subtitle: "",
    data: { rows: [] },
    entities: cities,
    focus,
    annotations: [],
  });

  it("brings a new scene forward and keeps the conversation's history", () => {
    stage.sync("c1", [scene("a")]);
    const before = stage.get().reveal;
    stage.sync("c1", [scene("a"), scene("b", ["Delhi"])]);
    const s = stage.get();
    expect(s.currentId).toBe("b");
    expect(s.focus).toEqual(["Delhi"]);
    expect(s.scenes.map((x) => x.id)).toEqual(["a", "b"]);
    expect(s.reveal).toBe(before + 1);
  });

  it("follows her voice, and a pointing is used once", () => {
    stage.sync("c2", [scene("x")]);
    stage.speech("Pune is the outlier today.", 0.5);
    expect(stage.get().focus).toEqual(["Pune"]);
    stage.point({ scene_id: "x", key: "Delhi", label: "Delhi", title: "x" });
    expect(stage.takePointing()?.label).toBe("Delhi");
    expect(stage.takePointing()).toBeNull();
  });
});
