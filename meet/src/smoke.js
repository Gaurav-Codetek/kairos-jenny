// A check of her body without a meeting: a page asks for a microphone and camera (as Meet does), gets her voice and
// her tile; a scene goes on the camera and a sentence is said. Screenshots of the camera land in out/.
import { chromium } from "playwright";

import { ARGS, bundle } from "./bundle.js";

const API = process.env.KAIROS_API || "http://api:8000";
const LINE = "Chennai and Delhi are carrying most of it today.";
const SCENE = {
  id: "smoke", kind: "breakdown", title: "Cancellation rate by city", subtitle: "Today so far against usual · 15:25",
  data: { rows: [
    { key: "Chennai", label: "Chennai", value: 0.09, display: "9.0%", usual: 0.068, usual_display: "6.8%" },
    { key: "Bangalore", label: "Bangalore", value: 0.06, display: "6.0%", usual: 0.051, usual_display: "5.1%" },
    { key: "Delhi", label: "Delhi", value: 0.082, display: "8.2%", usual: 0.073, usual_display: "7.3%" },
    { key: "Mumbai", label: "Mumbai", value: 0.068, display: "6.8%", usual: 0.052, usual_display: "5.2%" },
    { key: "Noida-1", label: "Noida-1", value: 0.13, display: "13.0%", usual: 0.068, usual_display: "6.8%", low_volume: true },
  ] },
  entities: ["Chennai", "Bangalore", "Delhi", "Mumbai", "Noida-1"].map((c) => ({ key: c, label: c, aliases: [c, c.replace(/-\d+$/, "")] })),
  focus: [], annotations: [{ key: "Chennai", text: "+8 vs its usual rate" }],
};

const browser = await chromium
  .launch({ headless: false, args: ARGS, channel: process.env.JENNY_BROWSER || "chrome" })
  .catch(() => chromium.launch({ headless: false, args: ARGS }));
const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, permissions: ["microphone", "camera"] });
await context.addInitScript({ content: bundle("Jenny (Kairos)") });
const page = await context.newPage();
const events = [];
await page.exposeBinding("__jennyEmit", (_s, e) => events.push(e));
// The microphone and camera exist only on secure pages, as on meet.google.com: serve the test page over https.
await page.route("https://jenny-smoke.test/**", (r) =>
  r.fulfill({ contentType: "text/html", body: '<video id="v" autoplay muted playsinline width="1280" height="720" style="background:#000"></video>' })
);
await page.goto("https://jenny-smoke.test/");
const tracks = await page.evaluate(async () => {
  const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
  document.getElementById("v").srcObject = s;
  return s.getTracks().map((t) => ({ kind: t.kind, state: t.readyState, label: t.label }));
});
await page.waitForTimeout(800);
await page.locator("#v").screenshot({ path: "out/camera-idle.png" });

await page.evaluate((s) => window.__jenny.scene(s), SCENE);
let said = "no audio (API unreachable)";
try {
  const r = await fetch(`${API}/api/v1/companion/voice/speak`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: LINE }),
  });
  if (r.ok) {
    const b64 = Buffer.from(await r.arrayBuffer()).toString("base64");
    await page.evaluate(([b, t]) => window.__jenny.say(1, b, t), [b64, LINE]);
    said = `said ${LINE.length} chars`;
  } else said = `voice ${r.status}`;
} catch (e) {
  said = String(e).slice(0, 120);
}
await page.waitForTimeout(1300);
await page.locator("#v").screenshot({ path: "out/camera-scene-mid.png" });
await page.waitForTimeout(2600);
await page.locator("#v").screenshot({ path: "out/camera-scene.png" });
console.log(JSON.stringify({ tracks, said, events }, null, 1));
await browser.close();
