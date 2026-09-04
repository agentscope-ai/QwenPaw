export interface CronJobScheduleCron {
  type: "cron";
  cron: string;
  timezone?: string;
}

export interface CronJobScheduleOnce {
  type: "once";
  run_at: string;
  timezone?: string;
  repeat_every_days?: number;
  repeat_end_type?: "never" | "until" | "count";
  repeat_until?: string;
  repeat_count?: number;
}

export type CronJobSchedule = CronJobScheduleCron | CronJobScheduleOnce;

export interface CronJobTarget {
  user_id: string;
  session_id: string;
}

export interface CronJobDispatch {
  type: "channel";
  channel?: string;
  target: CronJobTarget;
  mode?: "stream" | "final";
  silent?: boolean;
  meta?: Record<string, unknown>;
}

export interface CronJobRuntime {
  max_concurrency?: number;
  timeout_seconds?: number;
  misfire_grace_seconds?: number;
  tool_safety?: boolean;
}

export interface CronJobRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  request_context?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface CronJobPortabilityMeta {
  requires_review?: boolean;
  safety?: "disabled_until_explicit_promotion" | "reviewed_disabled" | string;
  source?: string;
  source_id?: string;
  source_cwd_remote_or_unverified?: boolean;
  source_cwd_binding?: string;
  promoted_at?: string;
  promoted_by?: string;
  [key: string]: unknown;
}

export interface CronJobMeta extends Record<string, unknown> {
  portability?: CronJobPortabilityMeta;
}

export interface CronJobSpecInput {
  id: string;
  name: string;
  enabled?: boolean;
  save_result_to_inbox?: boolean;
  schedule: CronJobSchedule;
  task_type?: "text" | "agent";
  text?: string;
  request?: CronJobRequest;
  dispatch: CronJobDispatch;
  runtime?: CronJobRuntime;
  meta?: CronJobMeta;
}

export type CronJobSpecOutput = CronJobSpecInput;

/**
 * Imported schedules are quarantined until the dedicated promotion endpoint
 * clears either form of the review gate. Keep this check shared by the hook
 * and every view so a stale or partially migrated record remains safe.
 */
export function requiresCronImportReview(
  job: Pick<CronJobSpecInput, "meta">,
): boolean {
  const portability = job.meta?.portability;
  return (
    portability?.requires_review === true ||
    portability?.safety === "disabled_until_explicit_promotion"
  );
}

export function requiresCronLocalProjectMapping(
  job: Pick<CronJobSpecInput, "meta">,
): boolean {
  const portability = job.meta?.portability;
  return (
    portability?.source_cwd_remote_or_unverified === true ||
    portability?.source_cwd_binding === "omitted_remote_or_unverified"
  );
}

export function getCronLocalProjectDir(
  job: Pick<CronJobSpecInput, "request">,
): string | undefined {
  const projectDir = job.request?.request_context?.project_dir;
  return typeof projectDir === "string" && projectDir.trim()
    ? projectDir.trim()
    : undefined;
}

export interface CronJobView extends CronJobSpecOutput {
  // Extended view with runtime state
  state?: unknown;
  next_run_time?: number;
  last_run_time?: number;
}

export interface CronJobExecutionRecord {
  run_at: string;
  status: "success" | "error" | "running" | "skipped" | "cancelled";
  error?: string | null;
  trigger?: "scheduled" | "manual";
}

export interface CronDispatchTargetItem {
  channel: string;
  user_id: string;
  session_id: string;
}

export interface CronDispatchTargetsResponse {
  channels: string[];
  items: CronDispatchTargetItem[];
}

export type CronJobSpecInputLegacy = Record<string, unknown>;
export type CronJobSpecOutputLegacy = Record<string, unknown>;
export type CronJobViewLegacy = Record<string, unknown>;
