export type ChatStatus = "idle" | "running";

export {
  RELAY_PROTOCOL_VERSION,
  assertRelayHeader,
  decodeRelayFrame,
  encodeRelayFrame,
  isRelayOperation,
  RELAY_OPERATIONS,
  type RelayFrame,
  type RelayFrameHeader,
  type RelayFrameType,
  type RelayOperation,
} from "./relay";
export type ChatSource = "chat" | "cron" | "subagent";
export type ChatGroupKind = "default" | "cron" | "subagents" | "custom";

export interface ChatGroup {
  id: string;
  name: string;
  order: number;
  kind: ChatGroupKind;
  source?: ChatSource | null;
  pinned: boolean;
}

export interface ChatSpec {
  id: string;
  session_id: string;
  user_id: string;
  channel: string;
  name?: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_finished_at?: string | null;
  meta?: Record<string, unknown>;
  status?: ChatStatus;
  pinned?: boolean;
  archived_at?: string | null;
  archived?: boolean;
  source?: ChatSource;
  group_id?: string | null;
  parent_session_id?: string | null;
  root_session_id?: string | null;
}

export interface ChatHistory<TMessage = unknown> {
  messages: TMessage[];
  status?: ChatStatus;
}

export interface PushMessage {
  id: string;
  text: string;
}

export interface InboxEvent {
  id: string;
  agent_id: string;
  source_type: string;
  source_id: string;
  event_type: string;
  status: string;
  severity: string;
  title: string;
  body: string;
  payload?: Record<string, unknown>;
  read: boolean;
  created_at: number;
}

export interface PendingApproval {
  request_id: string;
  session_id: string;
  root_session_id: string;
  owner_agent_id?: string;
  agent_id: string;
  tool_name: string;
  tool_display_name?: string;
  tool_source?: string;
  severity: string;
  findings_count: number;
  findings_summary: string;
  tool_params: Record<string, unknown>;
  created_at: number;
  timeout_seconds: number;
  reasoning?: string;
  is_generalized?: boolean;
  exact_target?: string;
  similar_target?: string;
  source_type: string;
}

export interface PushMessagesResponse {
  messages: PushMessage[];
  pending_approvals: PendingApproval[];
}

export type MobileNotificationKind =
  | "run_completed"
  | "input_required"
  | "approval_required"
  | "run_failed";

export type NotificationPreview = "full" | "title_only" | "hidden";

export interface NotificationPreferences {
  enabled: boolean;
  run_completed: boolean;
  input_required: boolean;
  approval_required: boolean;
  run_failed: boolean;
  preview: NotificationPreview;
}

export interface MobilePushSubscriptionRequest {
  installation_id: string;
  workspace_key: string;
  agent_id: string;
  platform: "android" | "ios";
  expo_push_token: string;
  preferences: NotificationPreferences;
}

export interface MobilePushSubscriptionResponse {
  installation_id: string;
  workspace_key: string;
  agent_id: string;
  platform: "android" | "ios";
  preferences: NotificationPreferences;
  updated_at: number;
}

export interface MobileNotificationData {
  version: 1;
  kind: MobileNotificationKind;
  workspace_key: string;
  agent_id: string;
  chat_id?: string;
  session_id?: string;
  approval_request_id?: string;
  inbox_event_id?: string;
}

export const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = {
  enabled: true,
  run_completed: true,
  input_required: true,
  approval_required: true,
  run_failed: true,
  preview: "title_only",
};

const NOTIFICATION_KINDS: ReadonlySet<string> = new Set([
  "run_completed",
  "input_required",
  "approval_required",
  "run_failed",
]);

const NOTIFICATION_PREVIEWS: ReadonlySet<string> = new Set([
  "full",
  "title_only",
  "hidden",
]);

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export function parseMobileNotificationData(
  value: unknown,
): MobileNotificationData | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  const kind = stringValue(item.kind);
  const workspaceKey = stringValue(item.workspace_key);
  const agentId = stringValue(item.agent_id);
  if (
    item.version !== 1 ||
    !kind ||
    !NOTIFICATION_KINDS.has(kind) ||
    !workspaceKey ||
    !agentId
  ) {
    return null;
  }
  return {
    version: 1,
    kind: kind as MobileNotificationKind,
    workspace_key: workspaceKey,
    agent_id: agentId,
    chat_id: stringValue(item.chat_id),
    session_id: stringValue(item.session_id),
    approval_request_id: stringValue(item.approval_request_id),
    inbox_event_id: stringValue(item.inbox_event_id),
  };
}

export function parseNotificationPreferences(
  value: unknown,
): NotificationPreferences | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (
    typeof item.enabled !== "boolean" ||
    typeof item.run_completed !== "boolean" ||
    typeof item.input_required !== "boolean" ||
    typeof item.approval_required !== "boolean" ||
    typeof item.run_failed !== "boolean" ||
    typeof item.preview !== "string" ||
    !NOTIFICATION_PREVIEWS.has(item.preview)
  ) {
    return null;
  }
  return item as unknown as NotificationPreferences;
}

export function notificationKindForInboxEvent(
  event: Pick<InboxEvent, "event_type" | "status" | "severity">,
): MobileNotificationKind | null {
  const eventType = event.event_type.toLowerCase();
  const status = event.status.toLowerCase();
  const severity = event.severity.toLowerCase();
  if (eventType.includes("approval")) return "approval_required";
  if (
    status === "failed" ||
    status === "error" ||
    severity === "error" ||
    severity === "critical"
  ) {
    return "run_failed";
  }
  if (eventType.includes("input") || status === "awaiting_user") {
    return "input_required";
  }
  if (status === "completed" || status === "success") {
    return "run_completed";
  }
  return null;
}

export function notificationPriority(kind: MobileNotificationKind): number {
  switch (kind) {
    case "approval_required":
      return 4;
    case "input_required":
      return 3;
    case "run_failed":
      return 2;
    case "run_completed":
      return 1;
  }
}
