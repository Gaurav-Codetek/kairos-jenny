"use client";

/**
 * Talk to Jenny, the companion — by typing, or on a voice call. She answers from the live data, her
 * moments and the monthly notebook, and shows which of her tools she used for each answer.
 * Conversations are kept: a refresh picks up the latest one, and earlier ones (calls included)
 * can be reopened from the history list.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, BellRing, Brain, Check, History, Mic, Phone, PhoneOff, Plus, Presentation, Scissors, Sparkles, X } from "lucide-react";

import { KairosMark, Spinner } from "@/components/kairos/ds";
import { timeAgo } from "@/components/agents/bits";
import { CallPill } from "@/components/living/jenny-call";
import { JackPill } from "@/components/living/jack-call";
import { NotePlay } from "@/components/living/voice-notes";
import { MeetingControl } from "@/components/living/meeting-control";
import type { Meeting } from "@/lib/meetings";
import { scenesOf, stage } from "@/lib/stage";
import { getChat, jackStatus, latestChat, listChats, newChat, prepareWelcome, say, withoutTones, type ChatSession, type ConversationSummary } from "@/lib/companion";
import { cn } from "@/lib/utils";

const SUGGESTIONS = ["How are we doing today?", "How did yesterday close?", "Which cities are carrying today?", "What should I keep an eye on this evening?"];

const TOOL_WORDS: Record<string, string> = {
  pulse_now: "checked the live pulse",
  moments: "read today's moments",
  compare_to_normal: "compared with a normal day",
  list_products: "looked at the data products",
  query: "queried live data",
  notebook: "read the monthly notebook",
  report_gap: "filed a report in Kairos",
  keep_watch: "kept an eye on it",
  check_later: "set a check for later",
  desk: "looked at her desk",
  drop_watch: "took it off her desk",
};

const MOVE_WORDS: Record<string, string> = {
  answer_brief: "brief answer",
  answer_deep: "full answer",
  ask_back: "asked back",
  empathise_then_answer: "empathy first",
  acknowledge: "acknowledged",
  raise_something: "raised something",
  small_talk: "small talk",
  wrap_up: "wrapped up",
};

/** "reaction · curious → acknowledged": how she read the turn, in a few words. */
function readLabel(b: NonNullable<ChatSession["messages"][number]["brain"]>): string {
  const kind = (b.turn ?? "").replace(/_/g, " ");
  const mood = b.emotion && b.emotion !== "neutral" ? ` · ${b.emotion}` : "";
  const move = b.move && (b.move_confidence ?? 0) >= 0.55 ? ` → ${MOVE_WORDS[b.move] ?? b.move}` : "";
  return `${kind}${mood}${move}`;
}

// Who takes the call, remembered in this browser: Jenny (Kairos's own pipeline) or Jack (an ElevenLabs Agent).
type Caller = "jenny" | "jack";
const CALLER_KEY = "kairos.callWith";
let callerHere: Caller = "jenny"; // when browser storage is unavailable
function readCaller(): Caller {
  try {
    return window.localStorage.getItem(CALLER_KEY) === "jack" ? "jack" : "jenny";
  } catch {
    return callerHere;
  }
}
function saveCaller(who: Caller) {
  callerHere = who;
  try {
    window.localStorage.setItem(CALLER_KEY, who);
  } catch {
    /* kept for this page only */
  }
  window.dispatchEvent(new Event(CALLER_KEY));
}
function subscribeCaller(onChange: () => void) {
  window.addEventListener(CALLER_KEY, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CALLER_KEY, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function CompanionChat({ workspaceId }: { workspaceId: string | null; headline?: string | null }) {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [calling, setCalling] = useState(false);
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  // Who takes the call: Jenny (Kairos's own pipeline) or Jack (an ElevenLabs Agent on the same data). Remembered here.
  const chosen = useSyncExternalStore(subscribeCaller, readCaller, () => "jenny" as const);
  // Jack is offered only while he's switched on (JACK_ENABLED); otherwise every call is Jenny's.
  const [jackOn, setJackOn] = useState(false);
  useEffect(() => {
    jackStatus()
      .then((r) => setJackOn(r.enabled))
      .catch(() => undefined);
  }, []);
  const callWith: Caller = jackOn ? chosen : "jenny";
  const pickCaller = (who: Caller) => saveCaller(who);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [past, setPast] = useState<ConversationSummary[] | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Pick up where the last conversation left off; and have the call's "welcome back" ready before it's needed.
  useEffect(() => {
    if (!workspaceId) return;
    prepareWelcome(workspaceId);
    let alive = true;
    latestChat(workspaceId)
      .then((s) => alive && setSession(s))
      .catch(() => alive && setError("Could not reach Jenny."));
    return () => {
      alive = false;
    };
  }, [workspaceId]);

  // Follow an answer while it is being written — one poller for the chat and the call alike, steady
  // while anything is pending (a timer recreated on every update would never get to fire).
  const sessionId = session?.id ?? null;
  const pending = session?.status === "running" || !!session?.messages.some((m) => m.pending);
  useEffect(() => {
    if (!sessionId || !pending) return;
    // On a call, often enough to speak each sentence as it is written.
    const t = window.setInterval(async () => {
      const s = await getChat(sessionId).catch(() => null);
      if (s) setSession(s);
    }, calling ? 350 : 700);
    return () => window.clearInterval(t);
  }, [sessionId, pending, calling]);

  // Between answers, look in now and then: Jenny may have raised something herself (a voice note).
  useEffect(() => {
    if (!sessionId || pending || calling) return;
    const t = window.setInterval(async () => {
      const s = await getChat(sessionId).catch(() => null);
      if (s) setSession((cur) => (cur && cur.id === s.id && cur.messages.length === s.messages.length ? cur : s));
    }, 60_000);
    return () => window.clearInterval(t);
  }, [sessionId, pending, calling]);

  // In a meeting: the chat follows the meeting's conversation, live.
  const meetingConv = meeting?.conversation_id ?? null;
  useEffect(() => {
    if (!meetingConv) return;
    let alive = true;
    const load = () => getChat(meetingConv).then((s) => alive && setSession(s)).catch(() => undefined);
    load();
    const t = window.setInterval(load, 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [meetingConv]);

  // Her scenes go on the stage as they arrive (while she's still working on the answer).
  useEffect(() => {
    if (session) stage.sync(session.id, scenesOf(session.messages));
  }, [session]);
  // A typed answer that's finished: light up what it names (on a call, her voice does this as she speaks).
  const lastDone = [...(session?.messages ?? [])].reverse().find((m) => m.role === "assistant" && !m.pending && m.scenes?.length);
  useEffect(() => {
    if (lastDone && !calling) stage.read(lastDone.text);
  }, [lastDone?.id, calling]); // eslint-disable-line react-hooks/exhaustive-deps

  const last = session?.messages[session.messages.length - 1];
  const scrollKey = `${session?.id}:${session?.messages.length ?? 0}:${last?.text.length ?? 0}:${last?.steps?.length ?? 0}:${last?.narration?.length ?? 0}:${last?.live?.length ?? 0}`;
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [scrollKey]);

  async function send(q: string, answering?: { message_id: string; answer: "yes" | "no" }) {
    const msg = q.trim();
    if (!msg || !session || pending) return;
    if (!answering) setText("");
    setError(null);
    const pointing = stage.takePointing();
    try {
      setSession(await say(session.id, msg, false, undefined, undefined, pointing, answering));
    } catch (e) {
      if (/still answering/i.test(String(e))) return;
      try {
        const s = await newChat(workspaceId!);
        setSession(await say(s.id, msg));
      } catch {
        setError("Could not send that — is the API running?");
      }
    }
  }

  async function openHistory() {
    const next = !historyOpen;
    setHistoryOpen(next);
    if (next && workspaceId) setPast((await listChats(workspaceId).catch(() => ({ conversations: [] }))).conversations);
  }

  async function startNew() {
    if (!workspaceId || calling) return;
    setHistoryOpen(false);
    setSession(await newChat(workspaceId));
  }

  async function reopen(id: string) {
    setHistoryOpen(false);
    if (calling) return;
    setSession(await getChat(id));
  }

  return (
    <aside className="relative flex min-h-0 flex-col border-l border-hairline bg-surface">
      <div className="flex items-center gap-2.5 border-b border-hairline px-4 py-3">
        <KairosMark size={22} />
        <div className="min-w-0 flex-1">
          <p className="text-k-title font-semibold text-ink">Ask Jenny</p>
          <p className="truncate text-k-caption text-ink-muted" title={session?.title ?? undefined}>
            {session?.title ?? "She answers from the live data, not from memory"}
          </p>
        </div>
        <button onClick={openHistory} className={cn("k-btn k-btn-ghost k-btn-sm px-2", historyOpen && "bg-sunken")} title="Earlier conversations" aria-label="Earlier conversations">
          <History className="h-4 w-4" />
        </button>
        <button onClick={startNew} disabled={calling || !workspaceId} className="k-btn k-btn-ghost k-btn-sm px-2" title="New conversation" aria-label="New conversation">
          <Plus className="h-4 w-4" />
        </button>
        {!calling && jackOn && (
          <div className="flex items-center rounded-full border border-hairline p-0.5" role="radiogroup" aria-label="Who takes the call">
            {(["jenny", "jack"] as const).map((who) => (
              <button
                key={who}
                role="radio"
                aria-checked={callWith === who}
                onClick={() => pickCaller(who)}
                title={who === "jenny" ? "Jenny: Kairos's own voice pipeline" : "Jack: an ElevenLabs Agent on the same data products and live pulse"}
                className={cn(
                  "rounded-full px-2 py-0.5 text-[11.5px] font-medium transition-colors",
                  callWith === who ? "bg-ink text-white" : "text-ink-muted hover:text-ink"
                )}
              >
                {who === "jenny" ? "Jenny" : "Jack"}
              </button>
            ))}
          </div>
        )}
        {!calling && (
          <button
            onClick={() => setCalling(true)}
            disabled={callWith === "jenny" ? !session : !workspaceId}
            className="k-btn k-btn-primary k-btn-sm"
            title={callWith === "jenny" ? "Talk to Jenny" : "Talk to Jack"}
          >
            <Phone className="h-3.5 w-3.5" /> Call
          </button>
        )}
      </div>

      {historyOpen && (
        <div className="k-rise absolute left-3 right-3 top-[60px] z-20 max-h-[60%] overflow-y-auto rounded-xl border border-hairline bg-surface p-1.5 shadow-lg">
          <p className="k-label px-2 py-1">Earlier conversations</p>
          {past === null ? (
            <p className="flex items-center gap-2 px-2 py-2 text-k-caption text-ink-muted">
              <Spinner /> Loading…
            </p>
          ) : past.length === 0 ? (
            <p className="px-2 py-2 text-k-caption text-ink-muted">Nothing yet.</p>
          ) : (
            past.map((c) => (
              <button
                key={c.id}
                onClick={() => reopen(c.id)}
                className={cn("flex w-full flex-col rounded-lg px-2 py-1.5 text-left hover:bg-sunken", c.id === session?.id && "bg-brand-soft")}
              >
                <span className="truncate text-[12.5px] font-medium text-ink">{c.title}</span>
                <span className="flex items-center gap-2 text-[11px] text-ink-subtle">
                  {timeAgo(c.last_at)} · {Math.ceil(c.messages / 2)} question{Math.ceil(c.messages / 2) === 1 ? "" : "s"}
                  {c.calls > 0 && (
                    <span className="inline-flex items-center gap-0.5">
                      · <Phone className="h-2.5 w-2.5" /> {c.calls} call{c.calls === 1 ? "" : "s"}
                    </span>
                  )}
                </span>
              </button>
            ))
          )}
        </div>
      )}

      {calling && workspaceId && callWith === "jenny" && (
        <CallPill workspaceId={workspaceId} session={session} onSession={setSession} onEnd={() => setCalling(false)} />
      )}
      {calling && workspaceId && callWith === "jack" && <JackPill workspaceId={workspaceId} onEnd={() => setCalling(false)} />}
      {!calling && <MeetingControl workspaceId={workspaceId} onMeeting={setMeeting} />}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {(session?.messages.length ?? 0) === 0 && (
          <div className="space-y-2">
            <p className="text-k-body text-ink-muted">Ask how the business is doing, why a number moved, or where it sits — or call me.</p>
            <div className="flex flex-col items-start gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} disabled={!session} className="k-btn k-btn-sm text-left">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {session?.messages.map((m, idx) =>
          m.role === "call" ? (
            <div key={m.id} className="flex items-center gap-2 py-0.5 text-[11px] text-ink-subtle">
              <span className="h-px flex-1 bg-hairline" />
              {m.call?.event === "end" ? <PhoneOff className="h-3 w-3" /> : <Phone className="h-3 w-3" />}
              {m.text} · {new Date(m.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
              <span className="h-px flex-1 bg-hairline" />
            </div>
          ) : m.role === "heard" ? (
            <p key={m.id} className="text-[12px] leading-snug text-ink-muted">
              <span className="font-semibold text-ink-2">{m.speaker ?? "Someone"}</span> {m.text}
            </p>
          ) : m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-soft px-3 py-2 text-k-body text-ink">
                {m.speaker && <span className="mb-0.5 block text-[11px] font-semibold text-brand-strong">{m.speaker} asked</span>}
                {m.voice && !m.speaker && <Mic className="-mt-0.5 mr-1 inline h-3 w-3 text-brand-strong" aria-label="said on a call" />}
                {m.text}
              </p>
            </div>
          ) : (
            <div key={m.id} className="k-rise space-y-1.5">
              {((m.steps?.length ?? 0) > 0 || m.from_memory || m.brain?.turn || m.proactive) && (
                <div className="flex flex-wrap gap-1">
                  {m.proactive && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-strong" title={m.proactive.title ?? "Something Jenny noticed"}>
                      <BellRing className="h-2.5 w-2.5" /> {m.proactive.recorded ? "Left while you were away" : "Heads-up"}
                    </span>
                  )}
                  {m.brain?.turn && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-[10.5px] text-ink-muted"
                      title={`How Jenny read your message (in ${m.brain.latency_ms ?? "?"} ms): ${m.brain.turn}, ${m.brain.emotion ?? "neutral"} → ${m.brain.move ?? "her own judgment"}, ${m.brain.tone ?? ""}`}
                    >
                      <Brain className="h-2.5 w-2.5 text-brand" />
                      {readLabel(m.brain)}
                    </span>
                  )}
                  {m.from_memory && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-strong" title="Answered from my earlier answer to the same question">
                      <Sparkles className="h-2.5 w-2.5" /> from memory · {m.from_memory.minutes_ago < 1 ? "just now" : `${m.from_memory.minutes_ago} min ago`}
                    </span>
                  )}
                  {m.steps?.map((s, i) => (
                    <span key={i} className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-[10.5px] text-ink-muted" title={JSON.stringify(s.args)}>
                      {s.ok ? <Check className="h-2.5 w-2.5 text-ok" /> : <X className="h-2.5 w-2.5 text-danger" />}
                      {TOOL_WORDS[s.tool] ?? s.tool}
                    </span>
                  ))}
                </div>
              )}
              {(m.narration?.length ?? 0) > 0 && (
                <div className="space-y-0.5 border-l-2 border-brand-soft pl-2.5">
                  {m.narration!.map((line, i) => (
                    <p key={i} className="text-[12px] italic leading-snug text-ink-muted">
                      {withoutTones(line)}
                    </p>
                  ))}
                </div>
              )}
              {m.pending ? (
                m.live ? (
                  <div className="eval-md text-k-body leading-relaxed text-ink">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{withoutTones(m.live) + " ▍"}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="flex items-center gap-2 text-k-body text-ink-muted">
                    <Spinner /> {(m.narration?.length ?? 0) > 0 ? "Working it out…" : "Thinking…"}
                  </p>
                )
              ) : (
                <div className={cn("eval-md text-k-body leading-relaxed text-ink", m.error && "text-danger", m.interrupted && "text-ink-muted")}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{withoutTones(m.text)}</ReactMarkdown>
                </div>
              )}
              {m.proactive?.recorded && m.proactive.audio && <NotePlay id={m.id} heard={m.proactive.heard} />}
              {/* She asked to do something: answer it in one tap (only on her latest message, until you reply). */}
              {m.offer && !m.pending && idx === session.messages.length - 1 && (
                <div className="flex items-center gap-2 pt-0.5">
                  <button
                    onClick={() => send("Yes, go ahead.", { message_id: m.id, answer: "yes" })}
                    disabled={pending}
                    className="k-btn k-btn-primary k-btn-sm h-7 px-3.5"
                    title={m.offer.question}
                  >
                    Yes
                  </button>
                  <button
                    onClick={() => send("No, thanks.", { message_id: m.id, answer: "no" })}
                    disabled={pending}
                    className="k-btn k-btn-sm h-7 px-3.5"
                    title={m.offer.question}
                  >
                    No
                  </button>
                </div>
              )}
              {(m.scenes?.length ?? 0) > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {m.scenes!.map((sc) => (
                    <button
                      key={sc.id}
                      onClick={() => stage.show(sc.id)}
                      className="inline-flex items-center gap-1.5 rounded-full border border-brand-border bg-brand-soft/60 px-2.5 py-1 text-[11px] font-medium text-brand-strong hover:bg-brand-soft"
                    >
                      <Presentation className="h-3 w-3" /> On stage: {sc.title}
                    </button>
                  ))}
                </div>
              )}
              {m.interrupted && (
                <p className="flex items-center gap-1 text-[11px] text-ink-subtle">
                  <Scissors className="h-3 w-3" /> You cut in{m.heard ? ` after: “${m.heard.slice(0, 90)}${m.heard.length > 90 ? "…" : ""}”` : " before she started"}
                </p>
              )}
            </div>
          )
        )}
        {error && <p className="text-k-caption text-danger">{error}</p>}
        <div ref={endRef} />
      </div>
      <form
        className="border-t border-hairline p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
      >
        <div className="flex items-end gap-2 rounded-xl border border-hairline bg-surface px-3 py-2 focus-within:border-brand">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(text);
              }
            }}
            rows={1}
            placeholder={pending ? "Answering…" : "Ask about today…"}
            className="max-h-32 min-h-[22px] flex-1 resize-none bg-transparent text-k-body text-ink outline-none placeholder:text-ink-subtle"
          />
          <button type="submit" disabled={!text.trim() || pending || !session} className="k-btn k-btn-primary k-btn-sm h-7 w-7 justify-center p-0" aria-label="Send">
            {pending ? <Spinner className="border-white/30" /> : <ArrowUp className="h-3.5 w-3.5" />}
          </button>
        </div>
      </form>
    </aside>
  );
}
