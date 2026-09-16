import { describe, expect, it } from "vitest";
import type { AgentsRunningConfig } from "@/api/types";
import { mergeRunningConfig } from "./configMerge";

type ConfigWithExtensions = AgentsRunningConfig & {
  server_extension?: { enabled: boolean; revision: number };
};

function originalConfig(): ConfigWithExtensions {
  return {
    max_iters: 40,
    loop: {
      iteration: { enabled: true, max_iterations: 40 },
      doom_loop: {
        enabled: true,
        window_size: 3,
        similarity_threshold: 0.9,
        stages: [{ after: 2, action: "warn", prompt: "old" }],
      },
      custom_modes: [],
    },
    shell_command_timeout: 60,
    shell_command_executable: "powershell.exe",
    llm_retry_enabled: true,
    llm_max_retries: 3,
    llm_backoff_base: 1,
    llm_backoff_cap: 10,
    llm_max_concurrent: 5,
    llm_max_qpm: 60,
    llm_rate_limit_pause: 1,
    llm_rate_limit_jitter: 0,
    llm_acquire_timeout: 30,
    history_max_length: 100,
    context_manager_backend: "light",
    light_context_config: {
      max_input_length: 1000,
      scroll_config: {
        db_filename: "history.db",
        history_retention_days: 30,
        allow_unsandboxed: false,
      },
      tool_result_pruning_config: {
        enabled: true,
        exempt_file_extensions: [".md", ".json"],
        exempt_tool_names: ["chat_with_agent", "read_file"],
      },
      visual_compact_config: { enabled: true, effort: "medium" },
    } as unknown as AgentsRunningConfig["light_context_config"],
    memory_manager_backend: "remelight",
    adbpg_memory_config: null,
    reme_light_memory_config: {
      needs_reindex: false,
      memory_search_enabled: true,
    } as AgentsRunningConfig["reme_light_memory_config"],
    approval_level: "AUTO",
    auto_title_config: { enabled: true, timeout_seconds: 30 },
    server_extension: { enabled: true, revision: 7 },
  };
}

describe("mergeRunningConfig", () => {
  it("preserves server-only and untouched nested fields", () => {
    const result = mergeRunningConfig(
      originalConfig(),
      {
        shell_command_timeout: 75,
        auto_title_config: { enabled: false },
        reme_light_memory_config: {
          needs_reindex: true,
        } as AgentsRunningConfig["reme_light_memory_config"],
      } as unknown as Partial<AgentsRunningConfig>,
      "STRICT",
    ) as ConfigWithExtensions;

    expect(result.shell_command_timeout).toBe(75);
    expect(result.auto_title_config).toEqual({
      enabled: false,
      timeout_seconds: 30,
    });
    expect(result.reme_light_memory_config).toEqual({
      needs_reindex: true,
      memory_search_enabled: true,
    });
    expect(result.light_context_config.visual_compact_config).toEqual({
      enabled: true,
      effort: "medium",
    });
    expect(result.server_extension).toEqual({ enabled: true, revision: 7 });
    expect(result.approval_level).toBe("STRICT");
  });

  it("replaces arrays instead of merging stale indexes", () => {
    const replacement = [{ after: 5, action: "stop", prompt: "new" }];
    const result = mergeRunningConfig(
      originalConfig(),
      {
        loop: {
          doom_loop: { stages: replacement },
        } as AgentsRunningConfig["loop"],
      },
      "AUTO",
    );

    expect(result.loop.doom_loop.stages).toEqual(replacement);
  });

  it("replaces the complete custom loop pipeline without stale gate metadata", () => {
    const original = originalConfig();
    original.loop.custom_modes = [
      {
        id: "old-mode",
        name: "Old mode",
        description: "old",
        slash_command: "old-mode",
        enabled: true,
        gates: [
          {
            id: "old-gate",
            type: "iteration",
            enabled: true,
            params: { max_iterations: 9 },
          },
        ],
      },
    ];
    const replacement = [
      {
        id: "quality-mode",
        name: "Quality mode",
        description: "preserve every field",
        slash_command: "quality-mode",
        enabled: true,
        gates: [
          {
            id: "rubric-gate",
            type: "completion_rubric" as const,
            enabled: true,
            params: {
              prompt: "Verify everything",
              completion_signal: "DONE",
              max_evaluations: 4,
            },
          },
        ],
      },
    ];

    const result = mergeRunningConfig(
      original,
      {
        loop: {
          custom_modes: replacement,
        } as unknown as AgentsRunningConfig["loop"],
      },
      "AUTO",
    );

    expect(result.loop.custom_modes).toEqual(replacement);
  });

  it("aligns legacy max_iters with the form iteration limit", () => {
    const result = mergeRunningConfig(
      originalConfig(),
      {
        loop: {
          iteration: { enabled: true, max_iterations: 91 },
        } as AgentsRunningConfig["loop"],
      },
      "SMART",
    );

    expect(result.loop.iteration?.max_iterations).toBe(91);
    expect(result.max_iters).toBe(91);
    expect(result.approval_level).toBe("SMART");
  });

  it("preserves collapsed context sections and replaces edited pruning lists", () => {
    const result = mergeRunningConfig(
      originalConfig(),
      {
        light_context_config: {
          context_compact_config: { compact_threshold_ratio: 0.75 },
          tool_result_pruning_config: {
            exempt_tool_names: ["search"],
          },
        } as AgentsRunningConfig["light_context_config"],
      },
      "AUTO",
    );

    expect(result.light_context_config.scroll_config).toEqual({
      db_filename: "history.db",
      history_retention_days: 30,
      allow_unsandboxed: false,
    });
    expect(result.light_context_config.visual_compact_config).toEqual({
      enabled: true,
      effort: "medium",
    });
    expect(
      result.light_context_config.tool_result_pruning_config
        ?.exempt_file_extensions,
    ).toEqual([".md", ".json"]);
    expect(
      result.light_context_config.tool_result_pruning_config?.exempt_tool_names,
    ).toEqual(["search"]);
  });

  it("preserves ReMe and ADBPG fields while switching memory backends", () => {
    const original = originalConfig();
    original.adbpg_memory_config = {
      rest_base_url: "https://adbpg.example/api",
      rest_api_key: "secret-key",
      memory_isolation: false,
      search_timeout: 15,
      auto_memory_search_config: { enabled: false, max_results: 8 },
    };
    original.reme_light_memory_config = {
      ...original.reme_light_memory_config,
      embedding_model_config: {
        backend: "openai",
        api_key: "embedding-key",
        base_url: "https://embedding.example/v1",
        model_name: "embedding-model",
        dimensions: 1024,
        enable_cache: true,
        use_dimensions: false,
        max_cache_size: 10000,
        max_input_length: 8192,
        max_batch_size: 10,
      },
    };

    const adbpg = mergeRunningConfig(
      original,
      { memory_manager_backend: "adbpg" },
      "AUTO",
    );
    const remelight = mergeRunningConfig(
      adbpg,
      { memory_manager_backend: "remelight" },
      "AUTO",
    );

    expect(remelight.adbpg_memory_config).toEqual(original.adbpg_memory_config);
    expect(remelight.reme_light_memory_config.embedding_model_config).toEqual(
      original.reme_light_memory_config.embedding_model_config,
    );
  });
});
