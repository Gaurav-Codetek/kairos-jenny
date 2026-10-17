// Linking what Jenny says to what's on her camera: which entities (a city, an hour) she has named so far in the
// sentence she's saying. The same logic as frontend/lib/stage.ts (mentions / focusAt), for the Meet tab.
(() => {
  const norm = (t) =>
    " " +
    String(t || "")
      .toLowerCase()
      .replace(/\[[a-z]+\]/g, " ")
      .replace(/[’‘]/g, "'")
      .replace(/[^a-z0-9.:'\- ]+/g, " ")
      .replace(/\s+/g, " ")
      .trim() +
    " ";
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function mentions(text, entities) {
    const t = norm(text);
    const found = [];
    for (const e of entities || []) {
      let best = -1;
      for (const a of [e.label, ...(e.aliases || [])]) {
        const n = norm(a).trim();
        if (!n) continue;
        const m = new RegExp(`(?<![a-z0-9])${esc(n)}(?![a-z0-9])`).exec(t);
        if (m && (best < 0 || m.index < best)) best = m.index;
      }
      if (best >= 0) found.push({ key: e.key, at: Math.max(0, best - 1) / Math.max(1, t.length - 2) });
    }
    return found.sort((a, b) => a.at - b.at);
  }

  function focusAt(text, progress, entities) {
    const all = mentions(text, entities);
    if (!all.length) return null;
    const said = all.filter((m) => m.at <= progress + 0.02).map((m) => m.key);
    return said.length ? said : null;
  }

  (typeof window !== "undefined" ? window : globalThis).__jennyCues = { mentions, focusAt };
})();
