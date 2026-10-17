// Jenny's body: a tiny control server. Kairos asks it to join a Google Meet (POST /sessions); each session is a
// Chromium window in the call that talks back to Kairos over a WebSocket (events in, commands out).
import http from "node:http";

import { finishSignIn, identity, signOut, signingIn, startSignIn } from "./identity.js";
import { MeetSession } from "./session.js";

const sessions = new Map();

function read(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  const send = (code, obj) => {
    res.writeHead(code, { "content-type": "application/json" });
    res.end(JSON.stringify(obj));
  };
  try {
    if (req.method === "GET" && req.url === "/health") return send(200, { ok: true, sessions: [...sessions.keys()] });
    // Jenny's own Google account
    if (req.method === "GET" && req.url === "/identity") return send(200, { ...identity(), signing_in: signingIn() });
    if (req.method === "POST" && req.url === "/identity/sign-in") return send(200, await startSignIn());
    if (req.method === "POST" && req.url === "/identity/done") return send(200, await finishSignIn());
    if (req.method === "DELETE" && req.url === "/identity") return send(200, await signOut());
    if (req.method === "POST" && req.url === "/sessions") {
      const body = JSON.parse((await read(req)) || "{}");
      if (!body.session_id || !/^https:\/\/meet\.google\.com\//.test(body.url || "") || !body.api_ws)
        return send(400, { error: "session_id, a meet.google.com url and api_ws are needed" });
      if (sessions.has(body.session_id)) return send(409, { error: "that session is already running" });
      const s = new MeetSession(body, () => sessions.delete(body.session_id));
      sessions.set(body.session_id, s);
      s.run(); // runs for the life of the meeting
      return send(202, { ok: true });
    }
    // What her Meet page has on it right now (buttons, caption area, chat box) and a screenshot: for fixing selectors.
    const dbg = (req.url || "").match(/^\/sessions\/([\w-]+)\/debug$/);
    if (req.method === "GET" && dbg) {
      const s = sessions.get(dbg[1]);
      return s ? send(200, await s.debug()) : send(404, { error: "no such session" });
    }
    const m = (req.url || "").match(/^\/sessions\/([\w-]+)$/);
    if (req.method === "DELETE" && m) {
      const s = sessions.get(m[1]);
      if (s) await s.leave();
      return send(200, { ok: !!s });
    }
    return send(404, { error: "not found" });
  } catch (e) {
    return send(500, { error: String(e) });
  }
});

server.listen(Number(process.env.PORT || 7070), () => console.log(`jenny-meet listening on ${process.env.PORT || 7070}`));
