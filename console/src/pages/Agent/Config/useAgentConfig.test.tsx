import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { AgentsRunningConfig } from "../../../api/types";

// vi.hoisted runs before the hoisted vi.mock factories, so the shared mock
// objects are available inside them.
const hoisted = vi.hoisted(() => {
  const mockSetFieldsValue = vi.fn();
  const mockValidateFields = vi.fn();
  const mockGetFieldsValue = vi.fn();
  const mockFormInstance = {
    setFieldsValue: mockSetFieldsValue,
    validateFields: mockValidateFields,
    getFieldsValue: mockGetFieldsValue,
  };
  const messageMock = {
    success: vi.fn(),
    error: vi.fn(),
  };
  const apiMocks = {
    getAgentRunningConfig: vi.fn(),
    getAgentLanguage: vi.fn(),
    getUserTimezone: vi.fn(),
    updateAgentRunningConfig: vi.fn(),
    updateAgentLanguage: vi.fn(),
    updateUserTimezone: vi.fn(),
  };
  const modalConfirmMock = vi.fn();
  // A stable translation function so useCallback dependencies don't change on
  // every render and trigger an infinite fetchConfig loop via useEffect.
  const stableT = (k: string) => k;
  return {
    mockSetFieldsValue,
    mockValidateFields,
    mockGetFieldsValue,
    mockFormInstance,
    messageMock,
    apiMocks,
    modalConfirmMock,
    stableT,
  };
});

vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  const passThrough = ({ children, ...props }: Record<string, unknown>) =>
    React.createElement("div", props, children as React.ReactNode);
  const Modal = Object.assign(passThrough, {
    confirm: hoisted.modalConfirmMock,
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  });
  const Form = Object.assign(passThrough, {
    Item: passThrough,
    useForm: () => [hoisted.mockFormInstance],
  });
  return { __esModule: true, Modal, Form };
});

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "agent-1" }),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: hoisted.stableT }),
}));

import { useAgentConfig } from "./useAgentConfig";

const {
  mockSetFieldsValue,
  mockValidateFields,
  mockGetFieldsValue,
  apiMocks,
  messageMock,
  modalConfirmMock,
} = hoisted;

type Config = AgentsRunningConfig;

function makeConfig(overrides: Partial<Config> = {}): Config {
  return {
    max_iters: 10,
    loop: {
      doom_loop: {
        enabled: true,
        window_size: 3,
        similarity_threshold: 1.0,
        stages: [],
      },
    },
    shell_command_timeout: 60,
    shell_command_executable: "",
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
    } as unknown as Config["light_context_config"],
    memory_manager_backend: "remelight",
    adbpg_memory_config: null,
    reme_light_memory_config:
      {} as unknown as Config["reme_light_memory_config"],
    approval_level: "AUTO",
    auto_title_config: { enabled: true, timeout_seconds: 30 },
    ...overrides,
  };
}

function renderConfigHook(onConfigLoaded?: (config: Config) => void) {
  return renderHook(() => useAgentConfig(onConfigLoaded));
}

describe("useAgentConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSetFieldsValue.mockReset();
    mockValidateFields.mockReset();
    mockGetFieldsValue.mockReset();
    apiMocks.getAgentRunningConfig.mockReset();
    apiMocks.getAgentLanguage.mockReset();
    apiMocks.getUserTimezone.mockReset();
    apiMocks.updateAgentRunningConfig.mockReset();
    apiMocks.updateAgentLanguage.mockReset();
    apiMocks.updateUserTimezone.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    modalConfirmMock.mockReset();

    apiMocks.getAgentRunningConfig.mockResolvedValue(makeConfig());
    apiMocks.getAgentLanguage.mockResolvedValue({ language: "en" });
    apiMocks.getUserTimezone.mockResolvedValue({ timezone: "UTC" });
    mockValidateFields.mockResolvedValue(makeConfig());
    mockGetFieldsValue.mockReturnValue(makeConfig());
  });

  it("initial loading=true, then loading=false after fetchConfig", async () => {
    let result: ReturnType<typeof renderConfigHook>;
    act(() => {
      result = renderConfigHook();
    });
    expect(result!.result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result!.result.current.loading).toBe(false);
    });
  });

  it("fetchConfig sets language from api.getAgentLanguage", async () => {
    apiMocks.getAgentLanguage.mockResolvedValue({ language: "fr" });
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.language).toBe("fr");
    });
  });

  it("fetchConfig sets timezone; falls back to UTC when response is empty", async () => {
    apiMocks.getUserTimezone.mockResolvedValue({ timezone: "" });
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.timezone).toBe("UTC");
    });
  });

  it("fetchConfig defaults approval_level to AUTO when missing", async () => {
    apiMocks.getAgentRunningConfig.mockResolvedValue(
      makeConfig({ approval_level: undefined }),
    );
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.approvalLevel).toBe("AUTO");
    });
  });

  it("fetchConfig uppercases an existing lowercased approval_level", async () => {
    apiMocks.getAgentRunningConfig.mockResolvedValue(
      makeConfig({ approval_level: "strict" }),
    );
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.approvalLevel).toBe("STRICT");
    });
  });

  it("fetchConfig sets error on failure", async () => {
    apiMocks.getAgentRunningConfig.mockRejectedValue(new Error("boom"));
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.error).toBe("boom");
    });
    expect(result.current.loading).toBe(false);
  });

  it("falls back context_manager_backend to 'light' when not in MAPPINGS", async () => {
    apiMocks.getAgentRunningConfig.mockResolvedValue(
      makeConfig({ context_manager_backend: "unknown-backend" }),
    );
    renderConfigHook();
    await waitFor(() => {
      expect(mockSetFieldsValue).toHaveBeenCalled();
    });
    const callArg = mockSetFieldsValue.mock.calls[0][0] as {
      context_manager_backend: string;
    };
    expect(callArg.context_manager_backend).toBe("light");
  });

  it("falls back memory_manager_backend to 'remelight' when not in MAPPINGS", async () => {
    apiMocks.getAgentRunningConfig.mockResolvedValue(
      makeConfig({ memory_manager_backend: "nope" }),
    );
    renderConfigHook();
    await waitFor(() => {
      expect(mockSetFieldsValue).toHaveBeenCalled();
    });
    const callArg = mockSetFieldsValue.mock.calls[0][0] as {
      memory_manager_backend: string;
    };
    expect(callArg.memory_manager_backend).toBe("remelight");
  });

  it("handleSave calls updateAgentRunningConfig and message.success on success", async () => {
    apiMocks.updateAgentRunningConfig.mockResolvedValue(makeConfig());
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(apiMocks.updateAgentRunningConfig).toHaveBeenCalledTimes(1);
    expect(messageMock.success).toHaveBeenCalledWith("agentConfig.saveSuccess");
  });

  it("reports the server config after save", async () => {
    const onConfigLoaded = vi.fn();
    const savedConfig = makeConfig({
      reme_light_memory_config: {
        needs_reindex: true,
      } as Config["reme_light_memory_config"],
    });
    apiMocks.updateAgentRunningConfig.mockResolvedValue(savedConfig);
    const { result } = renderConfigHook(onConfigLoaded);
    await waitFor(() => expect(result.current.loading).toBe(false));
    onConfigLoaded.mockClear();

    await act(async () => {
      await result.current.handleSave();
    });

    expect(onConfigLoaded).toHaveBeenCalledWith(savedConfig);
  });

  it("handleSave persists configToSave containing approval_level", async () => {
    apiMocks.updateAgentRunningConfig.mockResolvedValue(makeConfig());
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    act(() => {
      result.current.setApprovalLevel("STRICT");
    });

    await act(async () => {
      await result.current.handleSave();
    });

    const saved = apiMocks.updateAgentRunningConfig.mock.calls[0][0] as Config;
    expect(saved.approval_level).toBe("STRICT");
  });

  it("handleSave syncs legacy max_iters from loop.iteration.max_iterations", async () => {
    apiMocks.getAgentRunningConfig.mockResolvedValue(
      makeConfig({ max_iters: 100 }),
    );
    const loaded = makeConfig({ max_iters: 100 });
    const { max_iters: _staleMaxIters, ...formWithoutMaxIters } = loaded;
    mockGetFieldsValue.mockReturnValue({
      ...formWithoutMaxIters,
      loop: {
        ...loaded.loop,
        iteration: {
          enabled: true,
          max_iterations: 99,
        },
      },
    });
    apiMocks.updateAgentRunningConfig.mockResolvedValue(makeConfig());
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.handleSave();
    });

    const saved = apiMocks.updateAgentRunningConfig.mock.calls[0][0] as Config;
    expect(saved.loop.iteration?.max_iterations).toBe(99);
    expect(saved.max_iters).toBe(99);
  });

  it("handleSave includes unmounted custom loop template values", async () => {
    const customMode = {
      id: "quality",
      name: "Quality",
      description: "Review before stopping.",
      slash_command: "quality",
      enabled: true,
      gates: [
        {
          id: "rubric-1",
          type: "completion_rubric" as const,
          enabled: true,
          params: {
            prompt: "Every explicit requirement is complete.",
            completion_signal: "DONE",
          },
        },
      ],
    };
    mockValidateFields.mockResolvedValue({
      loop: { custom_modes: [{ name: "Quality" }] },
    });
    mockGetFieldsValue.mockReturnValue(
      makeConfig({
        loop: {
          doom_loop: {
            enabled: true,
            window_size: 3,
            similarity_threshold: 1,
            stages: [],
          },
          custom_modes: [customMode],
        },
      }),
    );
    apiMocks.updateAgentRunningConfig.mockResolvedValue(makeConfig());
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mockValidateFields).toHaveBeenCalledTimes(1);
    expect(mockGetFieldsValue).toHaveBeenCalledWith(true);
    const saved = apiMocks.updateAgentRunningConfig.mock.calls[0][0] as Config;
    expect(saved.loop.custom_modes).toEqual([customMode]);
  });

  it("handleSave calls message.error when update fails", async () => {
    apiMocks.updateAgentRunningConfig.mockRejectedValue(
      new Error("save failed"),
    );
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(messageMock.error).toHaveBeenCalledWith("save failed");
  });

  it("handleTimezoneChange calls updateUserTimezone and message.success", async () => {
    apiMocks.updateUserTimezone.mockResolvedValue({
      timezone: "Asia/Shanghai",
    });
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.handleTimezoneChange("Asia/Shanghai");
    });

    expect(apiMocks.updateUserTimezone).toHaveBeenCalledWith("Asia/Shanghai");
    expect(result.current.timezone).toBe("Asia/Shanghai");
    expect(messageMock.success).toHaveBeenCalledWith(
      "agentConfig.timezoneSaveSuccess",
    );
  });

  it("handleTimezoneChange does nothing when value equals current timezone", async () => {
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.timezone).toBe("UTC");
    });

    await act(async () => {
      await result.current.handleTimezoneChange("UTC");
    });

    expect(apiMocks.updateUserTimezone).not.toHaveBeenCalled();
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("handleLanguageChange opens Modal.confirm when value differs", async () => {
    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.language).toBe("en");
    });

    act(() => {
      result.current.handleLanguageChange("zh");
    });

    expect(modalConfirmMock).toHaveBeenCalledTimes(1);
    const options = modalConfirmMock.mock.calls[0][0] as { title: string };
    expect(options.title).toBe("agentConfig.languageConfirmTitle");
  });

  // -------------------------------------------------------------------------
  // #5137 — config lost when Collapse is not rendered
  // When a Collapse panel is collapsed (unrendered), form.getFieldsValue()
  // only returns currently registered fields. The deep-merge logic in
  // handleSave must preserve the original nested values from collapsed panels
  // so they are not lost on save.
  // -------------------------------------------------------------------------
  it("handleSave preserves collapsed (unrendered) nested config via deep merge (#5137)", async () => {
    const originalConfig = makeConfig({
      reme_light_memory_config: {
        needs_reindex: false,
        embedding_model: "text-embedding-v3",
        search_top_k: 5,
      } as unknown as Config["reme_light_memory_config"],
      light_context_config: {
        strategy: "scroll",
        context_compact_config: {
          enabled: true,
          compact_threshold_ratio: 0.8,
          reserve_threshold_ratio: 0.1,
        },
        scroll_config: {
          history_retention_days: 14,
        },
      } as unknown as Config["light_context_config"],
      adbpg_memory_config: {
        auto_search_enabled: true,
        auto_save_enabled: true,
        search_top_k: 10,
      } as unknown as Config["adbpg_memory_config"],
    });

    apiMocks.getAgentRunningConfig.mockResolvedValue(originalConfig);
    apiMocks.updateAgentRunningConfig.mockResolvedValue(originalConfig);

    // Simulate: only light_context_config.strategy is rendered (other panels collapsed).
    // getFieldsValue(true) returns partial nested objects.
    mockGetFieldsValue.mockReturnValue({
      light_context_config: {
        strategy: "native",
        // context_compact_config and scroll_config are MISSING because their
        // Collapse panels are collapsed (unrendered).
      },
      reme_light_memory_config: {
        // Only needs_reindex is rendered; embedding_model and search_top_k are
        // inside a collapsed sub-panel.
        needs_reindex: true,
      },
      // adbpg_memory_config is entirely inside a collapsed panel — not in form values at all.
    });

    const { result } = renderConfigHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.handleSave();
    });

    const saved = apiMocks.updateAgentRunningConfig.mock.calls[0][0] as Config;

    // The rendered field should be updated
    expect((saved.light_context_config as any).strategy).toBe("native");

    // The collapsed (unrendered) nested fields must be preserved from original
    expect(
      (saved.light_context_config as any).context_compact_config.enabled,
    ).toBe(true);
    expect(
      (saved.light_context_config as any).context_compact_config
        .compact_threshold_ratio,
    ).toBe(0.8);
    expect(
      (saved.light_context_config as any).scroll_config.history_retention_days,
    ).toBe(14);

    // reme_light_memory_config: rendered field updated, collapsed fields preserved
    expect((saved.reme_light_memory_config as any).needs_reindex).toBe(true);
    expect((saved.reme_light_memory_config as any).embedding_model).toBe(
      "text-embedding-v3",
    );
    expect((saved.reme_light_memory_config as any).search_top_k).toBe(5);

    // adbpg_memory_config: entirely collapsed — original values fully preserved
    expect((saved.adbpg_memory_config as any).auto_search_enabled).toBe(true);
    expect((saved.adbpg_memory_config as any).auto_save_enabled).toBe(true);
    expect((saved.adbpg_memory_config as any).search_top_k).toBe(10);
  });
});
