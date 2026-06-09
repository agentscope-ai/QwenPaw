export interface CronJobSchedule {
  type: "cron";
  cron: string;
  timezone?: string;
}

export interface CronJobTarget {
  user_id: string;
  session_id: string;
}

export interface CronJobDispatch {
  type: "channel";
  channel?: string;
  target: CronJobTarget;
  mode?: "stream" | "final";
  meta?: Record<string, unknown>;
}

export interface CronJobRuntime {
  max_concurrency?: number;
  timeout_seconds?: number;
  misfire_grace_seconds?: number;
}

export interface CronJobRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  [key: string]: unknown;
}

export interface CronJobSpecInput {
  id: string;
  name: string;
  enabled?: boolean;
  schedule: CronJobSchedule;
  task_type?: "text" | "agent";
  text?: string;
  request?: CronJobRequest;
  dispatch: CronJobDispatch;
  runtime?: CronJobRuntime;
  meta?: Record<string, unknown>;
}

export type CronJobSpecOutput = CronJobSpecInput;

export interface CronJobView extends CronJobSpecOutput {
  // Extended view with runtime state
  state?: unknown;
  next_run_time?: number;
  last_run_time?: number;
}

export type CronJobSpecInputLegacy = Record<string, unknown>;
export type CronJobSpecOutputLegacy = Record<string, unknown>;
export type CronJobViewLegacy = Record<string, unknown>;
