import { fetchApi } from "@/lib/api";

// Jenny in meetings: send her to a Google Meet, follow how it's going, ask her to leave.

export type MeetingState =
  | "starting"
  | "joining"
  | "waiting_to_be_admitted"
  | "in_meeting"
  | "left"
  | "ended"
  | "refused"
  | "removed"
  | "error";

export interface Meeting {
  id: string;
  url: string;
  state: MeetingState;
  error: string | null;
  conversation_id: string;
  participants: string[];
  started_at: string;
  joined_at: string | null;
  speaking: boolean;
  answering: boolean;
  recent: string[];
}

export const ENDED: MeetingState[] = ["left", "ended", "refused", "removed", "error"];
export const isLive = (m: Meeting) => !ENDED.includes(m.state);

export const joinMeeting = (workspaceId: string, url: string): Promise<Meeting> =>
  fetchApi(`/meetings`, { method: "POST", body: JSON.stringify({ workspace_id: workspaceId, url }) });

export const listMeetings = (workspaceId: string): Promise<{ meetings: Meeting[] }> =>
  fetchApi(`/meetings?workspace_id=${workspaceId}`);

export const leaveMeeting = (id: string): Promise<Meeting> => fetchApi(`/meetings/${id}`, { method: "DELETE" });

/** Where she is in a meeting, in words. */
export function meetingLabel(m: Meeting): string {
  const people = m.participants.length;
  switch (m.state) {
    case "starting":
      return "Starting her meeting client…";
    case "joining":
      return "Opening the meeting…";
    case "waiting_to_be_admitted":
      return "Waiting to be let in — admit “Jenny (Kairos)” in Meet";
    case "in_meeting":
      return `In the meeting${people ? ` · ${people} ${people === 1 ? "person" : "people"}` : ""} · ${
        m.speaking ? "speaking" : m.answering ? "working on an answer" : "listening"
      }`;
    case "refused":
      return m.error || "She wasn't let in";
    case "removed":
      return "She was removed from the meeting";
    case "ended":
      return "The meeting ended";
    case "left":
      return "She left the meeting";
    default:
      return m.error || "Something went wrong";
  }
}

// ── her own Google account ──

export interface Identity {
  signed_in: boolean;
  email?: string;
  name?: string;
  signing_in?: boolean;
  reason?: string;
}

export const getIdentity = (): Promise<Identity> => fetchApi(`/meetings/identity`);
/** Opens the one-time sign-in screen on her meeting machine; returns where to see it (this computer only). */
export const startSignIn = (): Promise<{ view_url: string }> => fetchApi(`/meetings/identity/sign-in`, { method: "POST" });
export const finishSignIn = (): Promise<Identity> => fetchApi(`/meetings/identity/done`, { method: "POST" });
export const signOut = (): Promise<Identity> => fetchApi(`/meetings/identity`, { method: "DELETE" });
