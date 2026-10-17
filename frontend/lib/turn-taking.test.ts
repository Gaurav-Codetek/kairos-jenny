import { describe, expect, it } from "vitest";

import { completeness, fuse, isOwnerSpeaking, PauseLearner, shouldEnd, withoutBackchannel } from "./turn-taking";

describe("completeness", () => {
  it("hears an unfinished thought", () => {
    expect(completeness("What about")).toBeLessThan(0.2);
    expect(completeness("So cancellations in Pune and")).toBeLessThan(0.2);
    expect(completeness("I was wondering if")).toBeLessThan(0.2);
  });
  it("hears a finished one", () => {
    expect(completeness("How are we doing today?")).toBeGreaterThanOrEqual(0.7);
    expect(completeness("How are we doing today")).toBeGreaterThanOrEqual(0.7);
  });
  it("leaves a short reply in between", () => {
    expect(completeness("Pune")).toBe(0.5);
  });
});

describe("shouldEnd", () => {
  it("answers a finished question after the usual pause, not before", () => {
    expect(shouldEnd(400, 0.8, 550)).toBe(false); // fairly sure: the usual pause
    expect(shouldEnd(600, 0.8, 550)).toBe(true);
  });
  it("waits through a mid-thought pause", () => {
    expect(shouldEnd(1500, 0.05, 550)).toBe(false);
    expect(shouldEnd(3500, 0.05, 550)).toBe(true);
  });
  it("gives a borderline turn a little longer", () => {
    expect(shouldEnd(900, 0.45, 550)).toBe(false);
    expect(shouldEnd(1300, 0.45, 550)).toBe(true);
  });
});

describe("PauseLearner", () => {
  it("starts at a sensible default and learns a slower speaker", () => {
    const p = new PauseLearner();
    expect(p.usualPause()).toBe(550);
    [700, 800, 900, 750, 850].forEach((ms) => p.record(ms));
    expect(p.usualPause()).toBeGreaterThan(900);
    expect(p.usualPause()).toBeLessThanOrEqual(1400);
  });
});

describe("withoutBackchannel", () => {
  it("removes her own mm-hm from the owner's words", () => {
    expect(withoutBackchannel("so the thing is mm-hm we need Pune")).toBe("so the thing is we need Pune");
    expect(withoutBackchannel("Mhm. what about GMV")).toBe("what about GMV");
  });
});

describe("fuse", () => {
  it("uses the words alone when the voice can't say", () => {
    expect(fuse(0.8, null)).toBe(0.8);
  });
  it("waits when both lean unfinished", () => {
    expect(fuse(0.3, 0.05)).toBe(0.05);
  });
  it("averages otherwise, so neither alone can cut you off or leave you waiting", () => {
    expect(fuse(0.95, 0.1)).toBeCloseTo(0.525);
    expect(fuse(0.1, 0.9)).toBeCloseTo(0.5);
  });
});

describe("isOwnerSpeaking", () => {
  const HER =
    "Delivered orders are on track today, about four thousand so far. Hyderabad is the one slipping, down about nine percent. Most of that gap is in the dinner hours.";
  // How many words, as they arrive, before she knows it's the owner.
  const wordsNeeded = (q: string, voiceHeard = false) => {
    const w = q.split(" ");
    for (let i = 1; i <= w.length; i++) if (isOwnerSpeaking(w.slice(0, i).join(" "), HER, voiceHeard)) return i;
    return Infinity;
  };
  it("hears the owner within two words, even when they reuse her words", () => {
    for (const q of ["how many orders were cancelled in Mumbai", "and what about Pune", "why is Hyderabad slipping",
      "can you check cancellations instead", "tell me about delivery times"])
      expect(wordsNeeded(q)).toBeLessThanOrEqual(2);
  });
  it("needs only a word once the microphone has heard a voice over hers", () => {
    expect(wordsNeeded("why is Hyderabad slipping", true)).toBe(1);
  });
  it("stops at once for a cue word", () => {
    expect(wordsNeeded("wait which city")).toBe(1);
  });
  it("never takes her own echo for the owner, misheard or not", () => {
    for (const e of ["delivered orders are on track to day", "hyderabad is the one slipping down about nine",
      "del ivered orders are on trek today", "most of that gap is in the dinner ours", "four thousand so far hyderabad",
      "orders are on track", "the one slipping"]) {
      expect(isOwnerSpeaking(e, HER)).toBe(false);
      expect(isOwnerSpeaking(e, HER, true)).toBe(false);
    }
  });
  it("lets a listener's mm-hm pass", () => {
    expect(isOwnerSpeaking("yeah okay", HER, true)).toBe(false);
  });
});

describe("shouldEnd, when sure", () => {
  it("ends a confidently finished turn after 0.3 s, not the usual pause", () => {
    expect(shouldEnd(320, 0.95, 900)).toBe(true);
    expect(shouldEnd(200, 0.95, 900)).toBe(false);
    expect(shouldEnd(320, 0.8, 900)).toBe(false); // less sure: the usual pause still applies
  });
});
