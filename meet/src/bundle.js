// What goes into the Meet tab (her microphone, camera and ears), and how Chromium is started for it.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { PAGE } from "./selectors.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS = ["cues.js", "camera.js", "media.js", "ears.js", "hearing.js"]
  .map((f) => fs.readFileSync(path.join(here, "inject", f), "utf8"))
  .join("\n;\n");

export const bundle = (name) =>
  `window.__JENNY_SEL = ${JSON.stringify(PAGE)}; window.__JENNY_NAME = ${JSON.stringify(name || "Jenny (Kairos)")};\n${SCRIPTS}`;

export const ARGS = [
  "--use-fake-ui-for-media-stream", // allow mic and camera without a prompt
  "--use-fake-device-for-media-stream", // devices exist; what they carry is replaced in the page
  "--autoplay-policy=no-user-gesture-required", // her voice plays without anyone clicking
  "--disable-blink-features=AutomationControlled",
  "--no-sandbox",
  "--lang=en-US",
  "--window-size=1280,1000",
  "--window-position=0,0",
];
