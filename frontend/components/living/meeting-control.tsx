"use client";

// Send Jenny to a Google Meet, and see where she is: opening it, waiting to be let in, in the meeting (listening,
// working on an answer, speaking), or out of it. While she's in one, the chat follows the meeting's conversation.

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, LogOut, UserRound, Video, X } from "lucide-react";

import { Spinner } from "@/components/kairos/ds";
import {
  finishSignIn,
  getIdentity,
  isLive,
  joinMeeting,
  leaveMeeting,
  listMeetings,
  meetingLabel,
  startSignIn,
  type Identity,
  type Meeting,
} from "@/lib/meetings";
import { cn } from "@/lib/utils";

export function MeetingControl({
  workspaceId,
  onMeeting,
}: {
  workspaceId: string | null;
  /** Her current meeting (or null): the chat follows its conversation. */
  onMeeting: (m: Meeting | null) => void;
}) {
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [who, setWho] = useState<Identity | null>(null);
  const [signing, setSigning] = useState(false);

  // Which account she joins as (her own, once signed in; otherwise a guest).
  useEffect(() => {
    let alive = true;
    getIdentity()
      .then((i) => {
        if (!alive) return;
        setWho(i);
        setSigning(!!i.signing_in);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  async function signIn() {
    setError(null);
    try {
      const { view_url } = await startSignIn();
      window.open(view_url, "_blank", "noopener");
      setSigning(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't open the sign-in screen.");
    }
  }

  async function done() {
    setBusy(true);
    setError(null);
    try {
      const i = await finishSignIn();
      setWho(i);
      setSigning(false);
      if (!i.signed_in) setError(i.reason || "She isn't signed in yet.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't check her sign-in.");
    } finally {
      setBusy(false);
    }
  }

  const apply = useCallback(
    (now: Meeting | null) => {
      setMeeting(now);
      onMeeting(now && isLive(now) ? now : null);
    },
    [onMeeting]
  );
  const refresh = useCallback(() => {
    if (!workspaceId) return;
    listMeetings(workspaceId)
      .then((r) => apply(r.meetings[0] ?? null))
      .catch(() => undefined);
  }, [workspaceId, apply]);

  useEffect(() => {
    if (!workspaceId) return;
    let alive = true;
    listMeetings(workspaceId)
      .then((r) => alive && apply(r.meetings[0] ?? null))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [workspaceId, apply]);

  const live = meeting && isLive(meeting);
  useEffect(() => {
    if (!live) return;
    const t = window.setInterval(refresh, 2500);
    return () => window.clearInterval(t);
  }, [live, refresh]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!workspaceId || !url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const m = await joinMeeting(workspaceId, url.trim());
      setMeeting(m);
      onMeeting(m);
      setOpen(false);
      setUrl("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send her to that meeting.");
    } finally {
      setBusy(false);
    }
  }

  if (live && meeting) {
    const waiting = meeting.state === "waiting_to_be_admitted";
    return (
      <div className="k-pop flex items-center gap-2.5 border-b border-hairline bg-brand-soft/50 px-4 py-2.5">
        <span className={cn("relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white", waiting ? "bg-warn-dot" : "bg-brand")}>
          <Video className="h-3.5 w-3.5" />
          {meeting.speaking && <span className="k-pulse absolute inset-0 rounded-full border-2 border-brand-border" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[12.5px] font-semibold text-ink">Jenny in Google Meet</p>
          <p className="truncate text-[11.5px] text-ink-muted" title={meetingLabel(meeting)}>
            {meetingLabel(meeting)}
          </p>
        </div>
        <button
          onClick={() => leaveMeeting(meeting.id).then(refresh).catch(() => undefined)}
          className="k-btn k-btn-sm h-7 px-2.5"
          title="Ask Jenny to leave the meeting"
        >
          <LogOut className="h-3.5 w-3.5" /> Leave
        </button>
      </div>
    );
  }

  return (
    <div className="border-b border-hairline px-4 py-2">
      {open ? (
        <form onSubmit={send} className="flex items-center gap-2">
          <label htmlFor="meet-url" className="sr-only">
            Google Meet link
          </label>
          <input
            id="meet-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://meet.google.com/abc-defg-hij"
            autoFocus
            className="h-8 min-w-0 flex-1 rounded-lg border border-hairline bg-surface px-2.5 text-[12.5px] text-ink outline-none focus:border-brand"
          />
          <button type="submit" disabled={busy || !url.trim()} className="k-btn k-btn-primary k-btn-sm h-8">
            {busy ? <Spinner className="border-white/30" /> : "Send her"}
          </button>
          <button type="button" onClick={() => setOpen(false)} className="text-ink-subtle hover:text-ink" aria-label="Cancel">
            <X className="h-4 w-4" />
          </button>
        </form>
      ) : (
        <div className="min-w-0">
          <button
            onClick={() => setOpen(true)}
            disabled={!workspaceId}
            className="flex items-center gap-1.5 whitespace-nowrap text-[12px] font-medium text-ink-muted hover:text-brand"
          >
            <Video className="h-3.5 w-3.5 shrink-0" /> Send Jenny to a Google Meet
          </button>
          {meeting && !isLive(meeting) && (
            <p className="mt-0.5 truncate pl-5 text-[11px] text-ink-subtle" title={meetingLabel(meeting)}>
              Last time: {meetingLabel(meeting)}
            </p>
          )}
          {/* Her account: meetings hosted by personal Google accounts don't admit signed-out guests. */}
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 pl-5 text-[11px]">
            <UserRound className="-ml-5 h-3 w-3 text-ink-subtle" />
            {signing ? (
              <>
                <span className="text-ink-muted">Sign her in on the screen that opened, then:</span>
                <button onClick={done} disabled={busy} className="font-semibold text-brand hover:underline">
                  {busy ? "Checking…" : "Done — I've signed her in"}
                </button>
                <button onClick={signIn} className="inline-flex items-center gap-0.5 text-ink-subtle hover:text-ink">
                  reopen <ExternalLink className="h-2.5 w-2.5" />
                </button>
              </>
            ) : who?.signed_in ? (
              <span className="truncate text-ink-muted" title={who.email}>
                Joins as {who.name || "her account"}
                {who.email ? ` (${who.email})` : ""}
              </span>
            ) : (
              <>
                <span className="text-ink-subtle">Joins as a guest ·</span>
                <button onClick={signIn} className="font-semibold text-brand hover:underline">
                  Sign Jenny in to her Google account
                </button>
              </>
            )}
          </div>
        </div>
      )}
      {error && <p className="mt-1.5 text-[11.5px] text-danger">{error}</p>}
    </div>
  );
}
