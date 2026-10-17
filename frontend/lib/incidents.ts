export interface Incident {
  run_id: string;
  entity_id: string;
  job_name: string | null;
  source_native_id: string;
  result_state: string;
  error_message: string | null;
  start_time: string | null;
  end_time: string | null;
  run_page_url: string | null;
}

/**
 * A readable title for a failed run. Platforms often leave the job name
 * empty, but the error names the task that broke ("Task X failed with
 * message: ..."), and the entity id carries the connection name.
 */
export function describeIncident(i: Incident): {
  title: string;
  message: string;
  workspace: string | null;
  duration: string | null;
} {
  const raw = i.error_message ?? "";
  const m = raw.match(/^Task (\S+) failed with message:\s*([\s\S]*)$/);
  const task = m?.[1] ?? null;
  const title = i.job_name || (task ? `Task ${task}` : `Run ${i.source_native_id}`);
  const message = (m ? m[2] : raw) || "No error message recorded";
  const workspace = i.entity_id.split(":")[1] ?? null;
  let duration: string | null = null;
  if (i.start_time && i.end_time) {
    const s = Math.max(0, (Date.parse(i.end_time) - Date.parse(i.start_time)) / 1000);
    duration = s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`;
  }
  return { title, message, workspace, duration };
}
