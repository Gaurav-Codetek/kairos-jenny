// Jenny's ears in the Meet tab: Meet's own live captions (each block carries the speaker's name), the Meet chat, and
// who's in the call. Read four times a second; only changes are reported. What to look for is in selectors.js.
(() => {
  const SEL = window.__JENNY_SEL || {};
  const emit = (e) => {
    try {
      window.__jennyEmit && window.__jennyEmit(e);
    } catch (_) {}
  };
  const first = (list, root = document) => {
    for (const s of list || []) {
      const el = root.querySelector(s);
      if (el) return el;
    }
    return null;
  };
  const all = (list, root = document) => {
    for (const s of list || []) {
      const els = root.querySelectorAll(s);
      if (els.length) return [...els];
    }
    return [];
  };

  // Meet puts its own controls inside a chat message (the pin button, its icon's name, a hint): not what was written
  const CHROME = /^(keep|keep_off|push_pin|more_vert|pin message|unpin message|hover over a message to pin it\.?|pinned)$/i;
  const chatText = (el) =>
    (el.innerText || "")
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s && !CHROME.test(s))
      .join(" ")
      .replace(/\s*Hover over a message to pin it\.?\s*/gi, " ")
      .trim();

  const ids = new WeakMap();
  let n = 0;
  const lastCaption = new Map();
  const seenChat = new Set();
  let lastPeople = "";

  function read() {
    // captions: one block per speaker turn; first line the name, the rest what they're saying
    const region = first(SEL.captionsRegion);
    if (region) {
      for (const block of region.children) {
        const lines = (block.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
        if (lines.length < 2) continue;
        if (!ids.has(block)) ids.set(block, `c${++n}`);
        const id = ids.get(block);
        const speaker = lines[0];
        const text = lines.slice(1).join(" ");
        const key = `${speaker}|${text}`;
        if (lastCaption.get(id) !== key) {
          lastCaption.set(id, key);
          emit({ type: "caption", block: id, speaker, text });
        }
      }
    }
    // chat
    for (const m of all(SEL.chatMessage)) {
      const mid = m.getAttribute("data-message-id");
      if (!mid || seenChat.has(mid)) continue;
      seenChat.add(mid);
      const holder = m.closest((SEL.chatSender || [])[0] || "[data-sender-name]");
      const text = chatText(m);
      if (text) emit({ type: "chat", sender: holder ? holder.getAttribute("data-sender-name") || "" : "", text });
    }
    // who's here (best effort: names on the video tiles)
    const names = [
      ...new Set(
        all(SEL.participantTile)
          .map((t) => (t.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean)[0])
          .filter(Boolean)
      ),
    ];
    const key = names.join("|");
    if (names.length && key !== lastPeople) {
      lastPeople = key;
      emit({ type: "participants", names });
    }
  }

  setInterval(() => {
    try {
      read();
    } catch (_) {}
  }, 250);
})();
