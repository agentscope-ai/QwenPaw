export interface Connection {
  baseUrl: string;
  token: string;
  username: string;
  agentId: string;
  source?: "platform" | "private";
  platformAccessPath?: string;
}

export interface AgentSummary {
  id: string;
  name: string;
  description?: string;
  enabled?: boolean;
  available_in_chat?: boolean;
  startup_status?: string;
  pinned?: boolean;
  backend?: string;
}

export type {
  ChatGroup,
  ChatSpec,
  PendingApproval,
} from "@qwenpaw/api-contract";

export interface ContentItem {
  type: string;
  text?: string;
  image_url?: string;
  video_url?: string;
  file_url?: string;
  file_name?: string;
  data?: string | Record<string, unknown>;
  [key: string]: unknown;
}

export interface WireMessage {
  id?: string;
  type?: string;
  role: string;
  content: string | ContentItem[] | Record<string, unknown>;
  [key: string]: unknown;
}

export interface ChatHistory {
  messages: WireMessage[];
  status?: "idle" | "running";
}

export interface DisplayMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  kind: "message" | "reasoning" | "tool";
  parts: DisplayPart[];
  toolName?: string;
  toolState?: string;
  toolCallId?: string;
  toolInput?: string;
  toolOutput?: string;
  pending?: boolean;
  error?: string;
}

export type DisplayPart =
  | { type: "text"; text: string }
  | { type: "image"; url: string; name?: string }
  | { type: "video"; url: string; name?: string }
  | { type: "audio"; url: string; name?: string }
  | { type: "file"; url: string; name: string };

export interface DisplayTurn {
  id: string;
  user: DisplayMessage | null;
  process: DisplayMessage[];
  answer: DisplayMessage | null;
  resultMedia: DisplayPart[];
  pending: boolean;
}

export interface UploadResult {
  url: string;
  file_name: string;
  size: number;
}

export type ApprovalLevel = "STRICT" | "SMART" | "AUTO" | "OFF";

export interface RunningConfig {
  approval_level?: string | null;
  [key: string]: unknown;
}

export interface ModelInfo {
  id: string;
  name: string;
  is_free?: boolean;
  is_recommended?: boolean;
  supports_multimodal?: boolean | null;
}

export interface ProviderInfo {
  id: string;
  name: string;
  api_key: string;
  base_url: string;
  models: ModelInfo[];
  extra_models: ModelInfo[];
  hidden_model_ids?: string[];
  is_custom: boolean;
  is_local: boolean;
  require_api_key: boolean;
  supports_oauth?: boolean;
  oauth_connected?: boolean;
  is_free_tier?: boolean;
}

export interface ActiveModelInfo {
  active_llm: {
    provider_id: string;
    model: string;
  } | null;
  effective_max_input_length?: number | null;
}

export interface ModelSlotOverride {
  provider_id: string;
  model: string;
}

export type LoopModeSource = "builtin" | "custom" | "plugin";
export type LoopSessionState =
  | "idle"
  | "starting"
  | "running"
  | "awaiting_user";

export interface LoopModeInfo {
  id: string;
  name: string;
  slash_command: string;
  description: string;
  source: LoopModeSource;
  name_i18n?: Record<string, string> | null;
  description_i18n?: Record<string, string> | null;
}

export interface LoopStatus {
  state: "idle" | "running" | "awaiting_user";
  mode: LoopModeInfo | null;
}
