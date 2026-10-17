"use client";

/**
 * A call with Jack: the same live business through an ElevenLabs Agent instead of Jenny's own pipeline.
 *
 * ElevenLabs runs the whole conversation (listening, turn-taking, its hosted model, the voice). Kairos gives Jack
 * only the data products and the live pulse, as client tools: when his model asks for one, this page runs it
 * against Kairos and hands the result back. The conversation token comes from Kairos, so the API key stays there.
 * An experiment beside Jenny: nothing of hers is used or changed.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Conversation } from "@elevenlabs/client";
import { Mic, MicOff, PhoneOff } from "lucide-react";

import { jackSession, jackTool } from "@/lib/companion";
import { cn } from "@/lib/utils";

type Phase = "connecting" | "listening" | "speaking" | "looking" | "ended" | "error";

const CAPTION: Record<Phase, string> = {
  connecting: "Connecting…",
  listening: "Listening",
  speaking: "Speaking",
  looking: "Looking at the data",
  ended: "Call ended",
  error: "Couldn't connect",
};

const TOOL_LABEL: Record<string, string> = {
  pulse_now: "the live dashboard",
  list_products: "the data products",
  query: "a live query",
  compare_to_normal: "a normal day",
};

function log(...args: unknown[]) {
  console.log("[jack]", ...args);
}

export function JackPill({ workspaceId, onEnd }: { workspaceId: string; onEnd: () => void }) {
  const [phase, setPhase] = useState<Phase>("connecting");
  const [line, setLine] = useState<{ who: "you" | "jack"; text: string } | null>(null);
  const [looking, setLooking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);
  const conv = useRef<Conversation | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await jackSession(workspaceId);
        if (cancelled) return;
        log("starting", s.agent_id, `(${s.llm}, ${s.voice})`);
        // Each tool runs here against Kairos; Jack's model gets the result.
        const tool = (name: string) => async (params: Record<string, unknown>) => {
          setLooking(TOOL_LABEL[name] ?? name);
          setPhase("looking");
          log("tool", name, params);
          try {
            return (await jackTool(workspaceId, name, params ?? {})).result;
          } catch (e) {
            return JSON.stringify({ error: e instanceof Error ? e.message : String(e) });
          } finally {
            setLooking(null);
          }
        };
        const c = await Conversation.startSession({
          conversationToken: s.conversation_token,
          connectionType: "webrtc",
          dynamicVariables: s.dynamic_variables,
          clientTools: {
            pulse_now: tool("pulse_now"),
            list_products: tool("list_products"),
            query: tool("query"),
            compare_to_normal: tool("compare_to_normal"),
          },
          onModeChange: ({ mode }) => setPhase(mode === "speaking" ? "speaking" : "listening"),
          onMessage: ({ message, source }) => {
            setLine({ who: source === "user" ? "you" : "jack", text: message });
            log(source === "user" ? "you:" : "jack:", message);
          },
          onError: (message) => {
            log("error", message);
            setError(String(message));
          },
          onDisconnect: () => setPhase((p) => (p === "error" ? p : "ended")),
        });
        if (cancelled) {
          c.endSession();
          return;
        }
        conv.current = c;
        // For testing in development: the live call, so a typed question can be sent to Jack.
        if (process.env.NODE_ENV !== "production") (window as unknown as { __jack?: Conversation }).__jack = c;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
      conv.current?.endSession().catch(() => undefined);
      conv.current = null;
    };
  }, [workspaceId]);

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      conv.current?.setMicMuted(!m);
      return !m;
    });
  }, []);

  const live = phase === "looking" && looking ? `Checking ${looking}…` : line ? (line.who === "you" ? `“${line.text}”` : line.text) : "";
  return (
    <div className="k-pop border-b border-hairline px-3 py-3">
      <div className="flex items-center gap-3 rounded-full border border-hairline bg-sunken py-2 pl-2 pr-2.5">
        <span className="relative flex h-14 w-14 shrink-0 items-center justify-center">
          {(phase === "speaking" || phase === "listening") &&
            [0, 1].map((i) => (
              <span
                key={i}
                className="k-pulse absolute inset-0 rounded-full"
                style={{
                  background: phase === "speaking" ? "var(--hairline)" : "transparent",
                  border: phase === "listening" ? "2px solid var(--hairline)" : "none",
                  animationDelay: `${i * 0.6}s`,
                }}
              />
            ))}
          {(phase === "looking" || phase === "connecting") && (
            <span className="k-spin absolute inset-0 rounded-full border-2 border-hairline border-t-ink" />
          )}
          <span
            className={cn(
              "relative flex h-11 w-11 items-center justify-center rounded-full bg-ink text-[18px] font-semibold text-white transition-transform duration-300",
              phase === "speaking" && "scale-110"
            )}
          >
            J
          </span>
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-k-body font-semibold text-ink">
            Jack
            <span className={cn("text-k-caption font-normal", phase === "error" ? "text-danger" : "text-ink-muted")}>
              · {muted && phase !== "error" ? "Microphone off" : CAPTION[phase]}
            </span>
          </p>
          <p className="truncate text-[12px] text-ink-2" title={error ?? live}>
            {error ? <span className="text-danger">{error}</span> : live || <span className="text-ink-subtle">ElevenLabs Agent · data products and the live pulse only</span>}
          </p>
        </div>
        <button
          onClick={toggleMute}
          disabled={phase === "error" || phase === "connecting"}
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition-colors",
            muted ? "border-transparent bg-ink text-white" : "border-hairline bg-surface text-ink-2 hover:bg-sunken"
          )}
          aria-label={muted ? "Turn microphone on" : "Turn microphone off"}
        >
          {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
        </button>
        <button
          onClick={onEnd}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-white"
          style={{ background: "var(--danger-dot)" }}
          aria-label="End call"
        >
          <PhoneOff className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
