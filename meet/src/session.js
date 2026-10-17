// One meeting: a Chromium window that joins a Google Meet as a guest named "Jenny (Kairos)".
//
// Inside the Meet tab (see inject/): her microphone is her voice, her camera is a canvas (her tile: her name, or the
// scene she's showing), and her ears are Meet's own captions. Kairos drives it over a WebSocket:
//   events out:  state · caption · chat · participants · spoken
//   commands in: say · stop · scene · status · chat_send · leave
import { chromium } from "playwright";
import WebSocket from "ws";

import { ARGS, bundle } from "./bundle.js";
import { PROFILE, clearLocks, identity, profileBusy, signingIn, useProfile } from "./identity.js";
import { S } from "./selectors.js";

const ADMIT_WAIT_MS = 10 * 60 * 1000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class MeetSession {
  constructor({ session_id, url, name, api_ws }, onDone) {
    Object.assign(this, { id: session_id, url, name: name || "Jenny (Kairos)", apiWs: api_ws, onDone });
    this.closed = false;
    this.state_ = "starting";
  }

  emit(obj) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  state(state, detail) {
    this.state_ = state;
    console.log(`[${this.id}] ${state}${detail ? `: ${detail}` : ""}`);
    this.emit({ type: "state", state, detail });
  }

  async connect() {
    this.ws = new WebSocket(this.apiWs);
    await new Promise((resolve, reject) => {
      this.ws.once("open", resolve);
      this.ws.once("error", reject);
    });
    this.ws.on("message", (raw) => this.command(JSON.parse(String(raw))).catch((e) => console.error(e)));
    this.ws.on("close", () => this.close());
  }

  async run() {
    try {
      await this.connect();
      // Signed in as her own Google account when she has one (meetings hosted by personal accounts don't admit
      // signed-out guests at all); otherwise a guest. Real Google Chrome either way, Chromium if it's missing.
      // The page fills a real window on the virtual screen (so Meet's controls and captions are on screen), with no
      // "controlled by automated test software" bar.
      const opts = { headless: false, args: ARGS, viewport: null, locale: "en-US", permissions: ["microphone", "camera"],
        ignoreDefaultArgs: ["--enable-automation"] };
      const channel = process.env.JENNY_BROWSER || "chrome";
      this.signedIn = identity().signed_in && !profileBusy() && !signingIn();
      if (this.signedIn) {
        // Her profile was made by Google Chrome: only Chrome opens it (an older Chromium hangs on it).
        clearLocks();
        useProfile(true);
        this.context = await chromium.launchPersistentContext(PROFILE, { ...opts, channel, timeout: 60000 });
      } else {
        const launch = { headless: false, args: ARGS, ignoreDefaultArgs: ["--enable-automation"] };
        this.browser = await chromium
          .launch({ ...launch, channel })
          .catch(() => chromium.launch(launch));
        this.context = await this.browser.newContext({ viewport: null, locale: "en-US", permissions: ["microphone", "camera"] });
      }
      await this.context.addInitScript({ content: bundle(this.name) });
      if (this.closed) return this.close(true); // asked to leave while still starting
      this.page = this.context.pages()[0] || (await this.context.newPage());
      await this.page.exposeBinding("__jennyEmit", (_src, evt) => this.emit(evt));
      this.page.on("close", () => this.close());
      this.state("joining");
      await this.page.goto(this.url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await this.join();
    } catch (e) {
      await this.snapshot("error");
      this.state("error", String(e?.message || e).slice(0, 300));
      await this.close();
    }
  }

  // ── joining ──
  async join() {
    const p = this.page;
    // The join screen, or a reason there won't be one (a wrong link, guests not allowed). Signed in, there's no name
    // to type: her account's name is used.
    const join = p.getByRole("button", { name: S.joinButton }).first();
    let name = null;
    let ready = false;
    const until = Date.now() + 30000;
    while (!ready && Date.now() < until) {
      if (await this.textMatches(S.badCode)) return this.endWith("error", "That Meet link doesn't exist — check the meeting code");
      if (await this.textMatches(S.blocked))
        return this.endWith("refused", this.signedIn
          ? "Google Meet won't let her account join this call"
          : "This meeting doesn't admit signed-out guests: sign Jenny in to her Google account first");
      name = await this.firstVisible(S.nameInput, 800);
      ready = !!name || (await join.isVisible().catch(() => false));
    }
    if (!ready) throw new Error("Couldn't find Meet's join screen");
    if (name) await name.fill(this.name);
    await this.clickIf(S.dismiss);
    await this.clickIf(S.micOn);
    await this.clickIf(S.camOn);
    await join.click({ timeout: 15000 });
    this.state("waiting_to_be_admitted");
    const started = Date.now();
    while (!this.closed && Date.now() - started < ADMIT_WAIT_MS) {
      if (await this.inCall()) return this.inMeeting();
      if (await this.textMatches(S.refused)) return this.endWith("refused", await this.why());
      await sleep(1000);
    }
    if (!this.closed) await this.endWith("refused", "No one admitted Jenny within 10 minutes");
  }

  // Which refusal: the words Meet shows differ, and so does what to do about it.
  async why() {
    if (await this.textMatches(S.denied)) return "The host declined Jenny's request to join";
    if (await this.textMatches(S.unanswered)) return "No one answered Jenny's request to join";
    return "Google Meet turned her request away before it reached the host (this meeting may not allow guests)";
  }

  async inMeeting() {
    this.state("in_meeting");
    await sleep(1500);
    await this.clickIf(S.dismiss);
    await this.ensureCaptions();
    this.watch();
  }

  // Captions are her ears: Meet shows "Turn on captions" while they're off; switched on whenever it does.
  async ensureCaptions() {
    if (await this.clickIf(S.captionsOn)) console.log(`[${this.id}] captions on`);
  }

  // The call ending, or her being removed; and her captions kept on.
  async watch() {
    while (!this.closed) {
      await sleep(2000);
      if (!this.page || this.page.isClosed()) return this.close();
      await this.ensureCaptions();
      if (!(await this.inCall())) {
        const removed = await this.textMatches(/removed/i);
        return this.endWith(removed ? "removed" : "ended");
      }
    }
  }

  async inCall() {
    return this.page.getByRole("button", { name: S.leave }).first().isVisible().catch(() => false);
  }

  // ── commands from Kairos ──
  async command(c) {
    if (!this.page || this.page.isClosed()) return;
    const call = (fn, ...args) => this.page.evaluate(([f, a]) => window.__jenny?.[f]?.(...a), [fn, args]).catch(() => {});
    if (c.type === "say") return call("say", c.id, c.audio, c.text);
    if (c.type === "stop") return call("stop");
    if (c.type === "scene") return call("scene", c.scene);
    if (c.type === "status") return call("status", c.status);
    if (c.type === "chat_send") return this.chat(c.text);
    if (c.type === "leave") return this.leave();
  }

  // The message box exists but stays hidden until the chat panel is open: open it, then write.
  async chat(text) {
    let box = await this.firstVisible(S.chatInput, 300);
    if (!box) {
      await this.clickIf(S.chatOpen);
      box = await this.firstVisible(S.chatInput, 6000);
    }
    if (!box) return console.warn(`[${this.id}] couldn't open the Meet chat`);
    try {
      await box.fill(text, { timeout: 5000 });
      await box.press("Enter");
    } catch (e) {
      console.warn(`[${this.id}] couldn't send a chat message: ${String(e).slice(0, 120)}`);
    }
  }

  async leave() {
    if (this.closed) return;
    if (!this.page) {
      // Still starting (opening Chrome): stop here; run() closes the browser as soon as it's up.
      this.state("left");
      this.closed = true;
      try { this.ws?.close(); } catch {}
      return this.onDone?.();
    }
    try {
      await this.page?.getByRole("button", { name: S.leave }).first().click({ timeout: 3000 });
    } catch {}
    await this.endWith("left");
  }

  async endWith(state, detail) {
    if (this.closed) return;
    if (state === "refused" || state === "error") await this.snapshot(state);
    this.state(state, detail);
    await this.close();
  }

  // Her Meet page as it is: for fixing selectors when Meet changes.
  async debug() {
    if (!this.page || this.page.isClosed()) return { error: "no page" };
    await this.snapshot("debug");
    return this.page.evaluate(() => {
      const vis = (e) => !!(e.offsetWidth || e.offsetHeight);
      return {
        url: location.href,
        jenny: { camera: !!window.__jenny, ears: !!window.__JENNY_SEL },
        buttons: [...document.querySelectorAll("button,[role=button]")]
          .filter(vis)
          .map((b) => b.getAttribute("aria-label") || (b.innerText || "").trim())
          .filter(Boolean)
          .slice(0, 90),
        regions: [...document.querySelectorAll("[role=region]")].map((r) => ({
          label: r.getAttribute("aria-label"), visible: vis(r), children: r.children.length, text: (r.innerText || "").slice(0, 240),
        })),
        live: [...document.querySelectorAll("[aria-live]")]
          .map((e) => ({ live: e.getAttribute("aria-live"), label: e.getAttribute("aria-label"), text: (e.innerText || "").slice(0, 200) }))
          .filter((x) => x.text),
        inputs: [...document.querySelectorAll("textarea,input,[contenteditable=true]")].map((t) => ({
          tag: t.tagName, label: t.getAttribute("aria-label"), placeholder: t.getAttribute("placeholder"), visible: vis(t),
        })),
      };
    });
  }

  // What she saw when something went wrong (Meet changes its page; this shows how).
  async snapshot(label) {
    try {
      await this.page?.screenshot({ path: `out/${this.id}-${label}.png` });
    } catch {}
  }

  async close(force = false) {
    if (this.closed && !force) return;
    this.closed = true;
    try { this.ws?.close(); } catch {}
    try { await (this.browser || this.context)?.close(); } catch {}
    if (this.signedIn) useProfile(false);
    this.onDone?.();
  }

  // ── helpers ──
  async firstVisible(selectors, timeout) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      for (const sel of selectors) {
        const loc = this.page.locator(sel).first();
        if (await loc.isVisible().catch(() => false)) return loc;
      }
      await sleep(300);
    }
    return null;
  }

  async clickIf(name) {
    const b = this.page.getByRole("button", { name }).first();
    if (await b.isVisible().catch(() => false)) {
      await b.click({ timeout: 3000 }).catch(() => {});
      return true;
    }
    return false;
  }

  async textMatches(re) {
    const t = await this.page.locator("body").innerText({ timeout: 2000 }).catch(() => "");
    return re.test(t);
  }
}
