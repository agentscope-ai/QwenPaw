import { vi } from "vitest";
import type {
  CreatorEvent,
  CreatorMessage,
  ExecutionAuthorizationView,
  FileProjectReviewOperation,
  FileProjectReviewRecord,
  SpecialistRunView,
} from "@/contracts/creator";
import type { ModelConfigData } from "@/contracts/creator/models";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";

/**
 * Resets every dock-related store, stubs localStorage, and seeds an idle
 * p1/session-1 Creator Session with a default conversation.
 */
export function seedCreatorSession() {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
      clear: vi.fn(),
    },
  });
  useAgentDockUiStore.getState().reset();
  useCreatorInteractionStore.getState().reset();
  useFileProjectReviewStore.getState().reset();
  useExecutionAuthorizationStore.getState().reset();
  useCreatorTaskViewStore.getState().reset();
  useCreatorSessionStore.getState().reset();
  useCreatorSessionStore.setState({
    projectId: "p1",
    session: {
      id: "session-1",
      projectId: "p1",
      status: "IDLE",
      lastMessageSeq: 0,
      lastConsumedMessageSeq: 0,
      lastEventSeq: 0,
    },
    conversations: [
      {
        conversationId: "conversation-1",
        title: "默认对话",
        isDefault: true,
        createdAt: "2026-07-11T00:00:00Z",
      },
    ],
    activeConversationId: "conversation-1",
    messages: [],
    queuedUi: [],
    events: [],
    hasMoreMessages: false,
    agentStatusBar: null,
  });
}

/**
 * Builds a CreatorMessage with a `text` sugar field for the common
 * single-text-part case. Defaults describe a plain user goal message.
 */
export function msg(
  overrides: Partial<CreatorMessage> & { text?: string } = {},
): CreatorMessage {
  const { text, ...rest } = overrides;
  return {
    messageId: "message-1",
    messageSeq: 1,
    role: "user",
    source: "initial_goal",
    content: text === undefined ? [] : [{ type: "text", text }],
    metadata: {},
    createdAt: "now",
    ...rest,
  };
}

/** Builds a CreatorEvent scoped to the default test project/session. */
export function evt(
  type: string,
  seq: number,
  data: Record<string, unknown>,
  overrides: Partial<CreatorEvent> = {},
): CreatorEvent {
  return {
    eventId: `${type}-${seq}`,
    seq,
    type,
    projectId: "p1",
    creatorSessionId: "session-1",
    at: "now",
    data,
    ...overrides,
  };
}

/** Builds a SpecialistRunView for the task-view store. */
export function makeRun(
  overrides: Partial<SpecialistRunView> = {},
): SpecialistRunView {
  return {
    id: "run-1",
    role: "visual_development_agent",
    displayName: "故事规划",
    status: "SUCCEEDED",
    targetRefs: [],
    taskRefs: [],
    metadata: {},
    ...overrides,
  };
}

/** Builds one pending file-project review operation. */
export function makeReviewOperation(
  overrides: Partial<FileProjectReviewOperation> = {},
): FileProjectReviewOperation {
  return {
    kind: "update",
    json_pointer: "/story/title",
    file_id: null,
    target_ref: null,
    before_hash: "before",
    after_hash: "after",
    before: "旧标题",
    after: "新标题",
    operation_id: "operation-1",
    ui_locator: {},
    decision: "PENDING",
    ...overrides,
  };
}

/** Builds a PENDING FileProjectReviewRecord with one default operation. */
export function makeReviewRecord(
  overrides: Partial<FileProjectReviewRecord> = {},
): FileProjectReviewRecord {
  return {
    review_id: "review-1",
    round_id: "round-1",
    request_id: "request-1",
    request_message_seq: 1,
    interrupted_run_id: "run-1",
    baseline_generation: 1,
    baseline_etag: "base-1",
    candidate_generation: 2,
    candidate_etag: "candidate-2",
    decision_token: "token-1",
    status: "PENDING",
    operations: [makeReviewOperation()],
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:01Z",
    ...overrides,
  };
}

/** Builds a PENDING execution authorization for the decision tray. */
export function makePendingAuthorization(
  overrides: Partial<ExecutionAuthorizationView> & Record<string, unknown> = {},
): ExecutionAuthorizationView {
  return {
    id: "authorization-1",
    transactionId: "round-1",
    specialistRunId: "run-1",
    executionRequestId: "request-1",
    targetRef: "element:el-1",
    scope: { operation: "image_generation" },
    status: "PENDING",
    authorizationToken: "token-1",
    provider: "dashscope",
    model: "qwen-image-2.0-pro",
    maxCandidates: 1,
    createdAt: "now",
    ...overrides,
  };
}

/** A fully configured model config so composer validation passes. */
export const configuredModelConfig: ModelConfigData = {
  llm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    multimodal: true,
  },
  vlm: {
    enabled: true,
    model_name: "qwen3.7-plus",
    api_key: "saved-secret",
    base_url: "https://example.test/v1",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    use_llm: true,
    multimodal: true,
  },
  grounding: {
    enabled: true,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "OpenAI 协议",
    custom_protocol: "",
    reuse_llm: true,
    validation_source: "llm",
    tavily_api_key: "",
    serper_api_key: "",
    native_search_enabled: true,
    search_provider: "dashscope_qwen",
    search_reuse_llm: true,
    search_model_name: "",
    search_api_key: "",
    search_base_url: "",
    search_protocol: "DashScope（百炼）",
  },
  asr: {
    enabled: false,
    model_name: "fun-asr",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope Fun-ASR",
    custom_protocol: "",
    provider: "fun-asr",
    language: "",
    reuse_llm_key: true,
  },
  tts: {
    enabled: false,
    model_name: "qwen3-tts-flash",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    voice: "",
    reuse_llm_key: true,
    vc_model_name: "",
  },
  s2v: {
    enabled: false,
    model_name: "",
    api_key: "",
    base_url: "",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    detect_model_name: "",
    reuse_llm_key: true,
  },
  embedding: {
    enabled: false,
    model_name: "qwen3-vl-embedding",
    api_key: "",
    base_url: "https://dashscope.aliyuncs.com/api/v1",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_vlm_key: true,
  },
  image: {
    enabled: true,
    model_name: "qwen-image",
    api_key: "",
    base_url: "https://example.test/image",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    translate_model: "",
    reuse_llm_key: true,
  },
  video: {
    enabled: true,
    model_name: "wan2.7-r2v",
    api_key: "",
    base_url: "https://example.test/video",
    protocol: "DashScope（百炼）",
    custom_protocol: "",
    reuse_llm_key: true,
  },
  oss: {
    enabled: false,
    access_key_id: "",
    access_key_secret: "",
    endpoint: "",
    bucket: "",
    public_base_url: "",
    policy_api_key: "",
  },
  executionAuthorization: { mode: "allow_all" },
  creationCheckpoints: { mode: "skip" },
  mediaReview: { mode: "required" },
  selfReview: {
    sync_enabled: false,
    media_enabled: false,
    render_enabled: false,
  },
};
