import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { SCREENS, WELCOME, screenGuide } from "./guides";

const root = fileURLToPath(new URL("..", import.meta.url));

/** Every data-guide value written in the app's source (the sidebar's nav:<href> ones from its NAV list). */
function marked(): Set<string> {
  const found = new Set<string>();
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.tsx$/.test(name)) {
        const src = readFileSync(p, "utf8");
        for (const m of src.matchAll(/data-guide="([^"]+)"/g)) found.add(m[1]);
        if (src.includes("data-guide={`nav:${href}`}")) {
          for (const m of src.matchAll(/\{ href: "([^"]+)", label:/g)) found.add(`nav:${m[1]}`);
        }
      }
    }
  };
  walk(join(root, "app"));
  walk(join(root, "components"));
  return found;
}

describe("guides", () => {
  it("the starter guide is eight steps, one for each part of the sidebar and one for the guides themselves", () => {
    expect(WELCOME.steps).toHaveLength(8);
    expect(WELCOME.steps.slice(0, 7).map((s) => s.target)).toEqual([
      "nav:/", "nav:/connections", "nav:/agents", "nav:/graph", "nav:/enrichment", "nav:/products", "nav:/living",
    ]);
  });

  it("every step points at something marked on a screen", () => {
    const targets = [WELCOME, ...Object.values(SCREENS)].flatMap((g) => g.steps.map((s) => s.target)).filter(Boolean);
    const have = marked();
    expect(targets.filter((t) => !have.has(t as string))).toEqual([]);
  });

  it("each screen in the sidebar has its own guide, and a detail page keeps its screen's", () => {
    for (const href of ["/", "/connections", "/agents", "/graph", "/enrichment", "/products", "/living"]) {
      expect(screenGuide(href)?.steps.length).toBeGreaterThan(0);
    }
    expect(screenGuide("/products/abc")?.id).toBe("products");
    expect(screenGuide("/evals")).toBeNull();
  });
});
