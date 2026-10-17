// Jenny's own Google account: a Chrome profile kept on a volume (/app/profile), signed in once by the owner.
//
// Signing in: a plain Google Chrome (not automated — Google refuses sign-ins it thinks are bots) opens the Google
// sign-in page on a second virtual screen, shown in the owner's browser through noVNC (localhost:6080). The owner
// types the password there; it never passes through Kairos. "Done" closes that Chrome and checks the profile is
// signed in. Meetings then open with this profile: she joins as her account, like a colleague.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { chromium } from "playwright";

import { ARGS } from "./bundle.js";

export const PROFILE = process.env.JENNY_PROFILE || "/app/profile";
const MARK = path.join(PROFILE, "jenny-identity.json");
const CHROME = process.env.JENNY_CHROME || "/opt/google/chrome/chrome";
const DISPLAY = ":50";
const VIEW_URL = process.env.JENNY_LOGIN_VIEW || "http://localhost:6080/vnc.html?autoconnect=1&resize=scale";

const procs = [];
let inUse = false;

export function identity() {
  try {
    return { signed_in: true, ...JSON.parse(fs.readFileSync(MARK, "utf8")) };
  } catch {
    return { signed_in: false };
  }
}

export const signingIn = () => procs.length > 0;

/** Chrome's "profile in use" locks, left behind when the machine restarts mid-session (they name a container that no
 *  longer exists, and Chrome then refuses the profile). Only cleared when nothing here has the profile open. */
export function clearLocks() {
  if (inUse || signingIn()) return;
  for (const f of ["SingletonLock", "SingletonSocket", "SingletonCookie"]) {
    try {
      fs.rmSync(path.join(PROFILE, f), { force: true });
    } catch {}
  }
}
export const profileBusy = () => inUse;
export const useProfile = (on) => (inUse = on);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function run(cmd, args, env = {}) {
  const p = spawn(cmd, args, { env: { ...process.env, ...env }, stdio: "ignore" });
  procs.push(p);
  return p;
}

/** Open the sign-in screen: a second virtual display, shown through noVNC, with a plain Chrome on Google sign-in. */
export async function startSignIn() {
  if (inUse) throw new Error("Jenny is in a meeting with her account; sign-in can wait until she leaves.");
  if (signingIn()) return { view_url: VIEW_URL };
  fs.mkdirSync(PROFILE, { recursive: true });
  clearLocks();
  run("Xvfb", [DISPLAY, "-screen", "0", "1280x800x24", "-nolisten", "tcp"]);
  await sleep(800);
  run("x11vnc", ["-display", DISPLAY, "-localhost", "-forever", "-shared", "-nopw", "-quiet", "-rfbport", "5900"]);
  run("websockify", ["--web", "/usr/share/novnc", "6080", "localhost:5900"]);
  run(CHROME, [`--user-data-dir=${PROFILE}`, "--no-first-run", "--no-default-browser-check", "--lang=en-US",
    "--window-size=1280,800", "--window-position=0,0", "--no-sandbox", "https://accounts.google.com/"], { DISPLAY });
  await sleep(1500);
  return { view_url: VIEW_URL };
}

async function stopSignIn() {
  for (const p of procs.splice(0).reverse()) {
    try {
      p.kill("SIGTERM");
    } catch {}
  }
  await sleep(2500); // Chrome writes its cookies on the way out
}

/** Close the sign-in screen and check the profile really is signed in (and as whom). */
export async function finishSignIn() {
  await stopSignIn();
  clearLocks();
  const ctx = await chromium.launchPersistentContext(PROFILE, { channel: "chrome", headless: false, args: ARGS,
    ignoreDefaultArgs: ["--enable-automation"], timeout: 60000 });
  try {
    const page = ctx.pages()[0] || (await ctx.newPage());
    await page.goto("https://myaccount.google.com/", { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(2500);
    const signedIn = page.url().startsWith("https://myaccount.google.com");
    if (!signedIn) {
      try { fs.rmSync(MARK); } catch {}
      return { signed_in: false, reason: "Google isn't showing a signed-in account yet. Sign in, then press Done again." };
    }
    const label = await page
      .locator('[aria-label^="Google Account"]')
      .first()
      .getAttribute("aria-label", { timeout: 5000 })
      .catch(() => "");
    const email = (label.match(/[\w.+-]+@[\w.-]+/) || [""])[0];
    const name = (label.match(/Google Account:\s*([^(\n]+)/) || ["", ""])[1].trim();
    const who = { email, name, signed_in_at: new Date().toISOString() };
    fs.writeFileSync(MARK, JSON.stringify(who));
    return { signed_in: true, ...who };
  } finally {
    await ctx.close().catch(() => {});
  }
}

/** Forget her account: the profile is wiped. */
export async function signOut() {
  if (inUse) throw new Error("She's in a meeting with her account.");
  await stopSignIn();
  fs.rmSync(PROFILE, { recursive: true, force: true });
  return { signed_in: false };
}
