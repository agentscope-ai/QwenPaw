import { host } from "./host";

async function request<T>(
  path: string,
  options: RequestInit & { timeout?: number } = {},
): Promise<T> {
  const { timeout = 30000, ...init } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const response = await host.fetch(path, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
    const body = await response.json();
    if (!response.ok)
      throw new Error(
        typeof body?.detail === "string"
          ? body.detail
          : `HTTP ${response.status}`,
      );
    return body as T;
  } finally {
    window.clearTimeout(timer);
  }
}

export interface RecordingFeature {
  enabled: boolean;
  supported_platform: boolean;
  capture_mode: "events-only";
}

export const recordingFeatureApi = {
  get: () =>
    request<RecordingFeature>("/desktop/recording/feature", { timeout: 5000 }),
  set: (enabled: boolean) =>
    request<RecordingFeature>("/desktop/recording/feature", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
};

export type RecordingState =
  | "starting"
  | "recording"
  | "paused"
  | "finalizing"
  | "completed"
  | "failed"
  | "interrupted"
  | "deleted";

export interface RecordingDescriptor {
  recording_id: string;
  agent_id: string;
  state: RecordingState;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  event_count: number;
  dropped_event_count: number;
  failure_code: string | null;
}

export interface DesktopRecordingStatus {
  api_schema_version: 1;
  available: boolean;
  input_monitoring: "granted" | "required" | "unavailable";
  accessibility: "granted" | "required" | "unavailable";
  state: "idle" | RecordingState;
  recording: RecordingDescriptor | null;
  last_recording: RecordingDescriptor | null;
}

export interface LearnModelTarget {
  provider_id: string;
  model: string;
  is_local: boolean;
}

export interface LearnEvidencePreview {
  api_schema_version: 1;
  recording_id: string;
  consent_token: string;
  expires_at: string;
  model_target: LearnModelTarget;
  external_transfer: boolean;
  persisted_event_count: number;
  selected_event_count: number;
  evidence_event_count: number;
  dropped_event_count: number;
  redacted_event_count: number;
  field_scope: string[];
}

export interface LearnEvidenceEvent {
  evidence_id: string;
  source_sequences: number[];
  type: "activate" | "drag" | "scroll" | "redacted_input";
  locator: SkillDraftStep["locator"];
  action: Record<string, unknown>;
  redacted: boolean;
}

export interface RecordingReview {
  api_schema_version: 1;
  recording_id: string;
  persisted_event_count: number;
  dropped_event_count: number;
  events: LearnEvidenceEvent[];
}

export interface SkillDraftInput {
  name: string;
  description: string;
  required: boolean;
}

export interface SkillDraftStep {
  source_event_id: string;
  action: "activate" | "drag" | "scroll" | "request-input";
  locator: {
    bundle_id: string | null;
    app_name: string | null;
    window_role: string | null;
    role: string | null;
    subrole: string | null;
    identifier: string | null;
    name: string | null;
  };
  instruction: string;
  verification: string;
}

export interface ReviewedSkillDraft {
  api_schema_version: 1;
  draft_id: string;
  recording_id: string;
  name: string;
  description: string;
  content: string;
  inputs: SkillDraftInput[];
  steps: SkillDraftStep[];
  source_sequences: number[];
  ignored_source_sequences: number[];
  ambiguities: string[];
  assumptions: string[];
  needs_confirmation: boolean;
}

export interface MaterializedSkill {
  api_schema_version: 1;
  created: true;
  name: string;
  enabled: boolean;
  reload_scheduled: boolean;
}

export function createRecordingApi(agentId: string) {
  const scopedRequest = <T>(
    path: string,
    options: RequestInit & { timeout?: number } = {},
  ) =>
    request<T>(path, {
      ...options,
      headers: { ...options.headers, "X-Agent-Id": agentId },
    });
  const mutate = (operation: "start" | "pause" | "resume" | "stop") =>
    scopedRequest<DesktopRecordingStatus>(`/desktop/recording/${operation}`, {
      method: "POST",
    });

  return {
    getStatus: () =>
      scopedRequest<DesktopRecordingStatus>("/desktop/recording", {
        timeout: 5000,
      }),
    requestPermission: () =>
      scopedRequest<DesktopRecordingStatus>(
        "/desktop/recording/permission/request",
        {
          method: "POST",
          timeout: 120000,
        },
      ),
    start: () => mutate("start"),
    pause: () => mutate("pause"),
    resume: () => mutate("resume"),
    stop: () => mutate("stop"),
    reviewRecording: (recordingId: string) =>
      scopedRequest<RecordingReview>("/desktop/recording/learn/review", {
        method: "POST",
        body: JSON.stringify({ recording_id: recordingId }),
      }),
    prepareLearn: (payload: {
      recording_id: string;
      goal: string;
      confirmed_context?: string;
      selected_sequences?: number[];
    }) =>
      scopedRequest<LearnEvidencePreview>("/desktop/recording/learn/prepare", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    generateDraft: (consentToken: string) =>
      scopedRequest<ReviewedSkillDraft>("/desktop/recording/learn/generate", {
        method: "POST",
        body: JSON.stringify({ consent_token: consentToken, consent: true }),
        timeout: 60000,
      }),
    recoverDraft: (recordingId: string) =>
      scopedRequest<ReviewedSkillDraft | null>(
        `/desktop/recording/learn/draft/${recordingId}`,
        { timeout: 5000 },
      ),
    materializeSkill: (payload: {
      draft_id: string;
      name: string;
      content: string;
    }) =>
      scopedRequest<MaterializedSkill>("/desktop/recording/learn/materialize", {
        method: "POST",
        body: JSON.stringify({ ...payload, approved: true }),
        timeout: 60000,
      }),
  };
}
