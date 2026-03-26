import { describe, expect, it } from "vitest";
import {
  deriveRuntimeStatusSnapshot,
  formatTokenCount,
  mergeRuntimeStatusSnapshot,
} from "./chatRuntimeStatus";

describe("chatRuntimeStatus", () => {
  it("uses configured context window and max_tokens when present", () => {
    const snapshot = deriveRuntimeStatusSnapshot({
      providers: [
        {
          id: "lmstudio",
          name: "LM Studio",
          api_key_prefix: "",
          chat_model: "qwen3.5:27b",
          models: [],
          extra_models: [],
          is_custom: false,
          is_local: true,
          support_model_discovery: true,
          support_connection_check: true,
          freeze_url: false,
          require_api_key: false,
          api_key: "",
          base_url: "http://127.0.0.1:1234/v1",
          generate_kwargs: {
            max_tokens: 4096,
            context_length: 400000,
          },
        },
      ],
      activeModels: {
        active_llm: {
          provider_id: "lmstudio",
          model: "qwen3.5:27b",
        },
      },
      runningConfig: {
        max_iters: 50,
        llm_retry_enabled: true,
        llm_max_retries: 2,
        llm_backoff_base: 1,
        llm_backoff_cap: 8,
        token_count_model: "default",
        token_count_estimate_divisor: 3.75,
        token_count_use_mirror: false,
        max_input_length: 30000,
        memory_compact_ratio: 0.8,
        memory_reserve_ratio: 0.9,
        tool_result_compact_recent_n: 4,
        tool_result_compact_old_threshold: 1200,
        tool_result_compact_recent_threshold: 2400,
        tool_result_compact_retention_days: 7,
        knowledge_enabled: true,
        knowledge_auto_collect_chat_files: true,
        knowledge_auto_collect_chat_urls: true,
        knowledge_auto_collect_long_text: true,
        knowledge_long_text_min_chars: 500,
        knowledge_chunk_size: 1000,
      },
      chatHistory: {
        messages: [
          { role: "user", content: [{ type: "text", text: "请帮我重构这个 pipeline 并补充校验节点" }] },
          { role: "assistant", content: [{ type: "text", text: "好的，我先分析现有步骤。" }] },
          { role: "tool", content: [{ type: "tool_result", text: "long tool output".repeat(100) }] },
          { role: "user", content: [{ type: "file", url: "/console/files/default/spec.md", text: "spec.md" }] },
        ],
      },
    });

    expect(snapshot.context_window_tokens).toBe(400000);
    expect(snapshot.reserved_response_tokens).toBe(4096);
    expect(snapshot.used_tokens).toBeGreaterThan(0);
    expect(snapshot.breakdown.find((item) => item.key === "tool-results")?.tokens).toBeGreaterThan(0);
    expect(snapshot.breakdown.find((item) => item.key === "files")?.tokens).toBeGreaterThan(0);
  });

  it("falls back to derived context window when provider does not expose one", () => {
    const snapshot = deriveRuntimeStatusSnapshot({
      providers: [
        {
          id: "ollama",
          name: "Ollama",
          api_key_prefix: "",
          chat_model: "qwen3.5:27b",
          models: [],
          extra_models: [],
          is_custom: false,
          is_local: true,
          support_model_discovery: true,
          support_connection_check: true,
          freeze_url: false,
          require_api_key: false,
          api_key: "",
          base_url: "http://127.0.0.1:11434",
          generate_kwargs: { max_tokens: 4096 },
        },
      ],
      activeModels: {
        active_llm: { provider_id: "ollama", model: "qwen3.5:27b" },
      },
      runningConfig: {
        max_iters: 50,
        llm_retry_enabled: true,
        llm_max_retries: 2,
        llm_backoff_base: 1,
        llm_backoff_cap: 8,
        token_count_model: "default",
        token_count_estimate_divisor: 3.75,
        token_count_use_mirror: false,
        max_input_length: 30000,
        memory_compact_ratio: 0.8,
        memory_reserve_ratio: 0.9,
        tool_result_compact_recent_n: 4,
        tool_result_compact_old_threshold: 1200,
        tool_result_compact_recent_threshold: 2400,
        tool_result_compact_retention_days: 7,
        knowledge_enabled: true,
        knowledge_auto_collect_chat_files: true,
        knowledge_auto_collect_chat_urls: true,
        knowledge_auto_collect_long_text: true,
        knowledge_long_text_min_chars: 500,
        knowledge_chunk_size: 1000,
      },
      chatHistory: { messages: [] },
    });

    expect(snapshot.context_window_tokens).toBeGreaterThan(34000);
  });

  it("formats token counts in K units", () => {
    expect(formatTokenCount(134200)).toBe("134.2K");
    expect(formatTokenCount(980)).toBe("980");
  });

  it("only merges transient data when snapshot ownership matches current chat", () => {
    const merged = mergeRuntimeStatusSnapshot(
      {
        scope_level: "chat",
        snapshot_source: "runtime_push",
        snapshot_stage: "pre_model_call",
        agent_id: "default",
        session_id: "session-a",
        user_id: "user-a",
        chat_id: "chat-a",
        context_window_tokens: 10000,
        used_tokens: 1000,
        used_ratio: 0.1,
        reserved_response_tokens: 500,
        remaining_tokens: 8500,
        model_id: "qwen",
        provider_id: "ollama",
        profile_label: "Local runtime",
        breakdown: [
          { key: "system-instructions", label: "System Instructions", tokens: 400, ratio: 0.04, section: "system" },
          { key: "tool-definitions", label: "Tool Definitions", tokens: 300, ratio: 0.03, section: "system" },
          { key: "messages", label: "Messages", tokens: 300, ratio: 0.03, section: "user" },
          { key: "tool-results", label: "Tool Results", tokens: 0, ratio: 0, section: "user" },
          { key: "files", label: "Files", tokens: 0, ratio: 0, section: "user" },
        ],
      },
      {
        chatHistory: {
          messages: [{ role: "user", content: "hello world" }],
        },
      },
      {
        expectedAgentId: "default",
        expectedChatId: "chat-a",
        expectedSnapshotStage: "pre_model_call",
      },
    );

    expect(merged.snapshot_source).toBe("runtime_push");
    expect(merged.used_tokens).toBeGreaterThan(1000);
  });

  it("falls back to frontend estimate when snapshot ownership does not match current chat", () => {
    const merged = mergeRuntimeStatusSnapshot(
      {
        scope_level: "chat",
        snapshot_source: "runtime_push",
        snapshot_stage: "pre_model_call",
        agent_id: "other-agent",
        session_id: "session-a",
        user_id: "user-a",
        chat_id: "chat-other",
        context_window_tokens: 10000,
        used_tokens: 1000,
        used_ratio: 0.1,
        reserved_response_tokens: 500,
        remaining_tokens: 8500,
        model_id: "qwen",
        provider_id: "ollama",
        profile_label: "Local runtime",
        breakdown: [],
      },
      {
        chatHistory: {
          messages: [{ role: "user", content: "hello world" }],
        },
      },
      {
        expectedAgentId: "default",
        expectedChatId: "chat-a",
        expectedSnapshotStage: "pre_model_call",
      },
    );

    expect(merged.snapshot_source).toBe("frontend_estimate");
    expect(merged.agent_id).toBeNull();
    expect(merged.chat_id).toBeNull();
  });

  it("falls back to frontend estimate when backend snapshot is only empty baseline", () => {
    const merged = mergeRuntimeStatusSnapshot(
      {
        scope_level: "chat",
        snapshot_source: "empty_baseline",
        snapshot_stage: "pre_model_call",
        agent_id: "default",
        session_id: "session-a",
        user_id: "user-a",
        chat_id: "chat-a",
        context_window_tokens: 10000,
        used_tokens: 0,
        used_ratio: 0,
        reserved_response_tokens: 500,
        remaining_tokens: 9500,
        model_id: "qwen",
        provider_id: "ollama",
        profile_label: "Cloud/runtime",
        breakdown: [
          { key: "system-instructions", label: "System Instructions", tokens: 0, ratio: 0, section: "system" },
          { key: "tool-definitions", label: "Tool Definitions", tokens: 0, ratio: 0, section: "system" },
          { key: "messages", label: "Messages", tokens: 0, ratio: 0, section: "user" },
          { key: "tool-results", label: "Tool Results", tokens: 0, ratio: 0, section: "user" },
          { key: "files", label: "Files", tokens: 0, ratio: 0, section: "user" },
        ],
      },
      {
        chatHistory: {
          messages: [{ role: "user", content: "hello world" }],
        },
      },
      {
        expectedAgentId: "default",
        expectedChatId: "chat-a",
        expectedSnapshotStage: "pre_model_call",
      },
    );

    expect(merged.snapshot_source).toBe("frontend_estimate");
    expect(merged.used_tokens).toBeGreaterThan(0);
    expect(merged.chat_id).toBeNull();
  });
});