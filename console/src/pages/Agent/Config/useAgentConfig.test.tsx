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
    warning: vi.fn(),
    error: vi.fn(),
  };
  const apiMocks = {
    getAgentRunningConfigAccess: vi.fn(),
    getAgentRunningConfigSummary: vi.fn(),
    getAgentRunningConfig: vi.fn(),
    getAgentRunningConfigVersion: vi.fn(),
    getAgentRunningConfigRuntimeStatus: vi.fn(),
    retryAgentRunningConfigReload: vi.fn(),
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

function renderConfigHook(
  onConfigLoaded?: (config: Config) => void,
  governanceAgentId?: string,
) {
  return renderHook(() => useAgentConfig(onConfigLoaded, governanceAgentId));
}

describe("useAgentConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSetFieldsValue.mockReset();
    mockValidateFields.mockReset();
    mockGetFieldsValue.mockReset();
    apiMocks.getAgentRunningConfig.mockReset();
    apiMocks.getAgentRunningConfigAccess.mockReset();
    apiMocks.getAgentRunningConfigSummary.mockReset();
    apiMocks.getAgentRunningConfigVersion.mockReset();
    apiMocks.getAgentRunningConfigRuntimeStatus.mockReset();
    apiMocks.retryAgentRunningConfigReload.mockReset();
    apiMocks.getAgentLanguage.mockReset();
    apiMocks.getUserTimezone.mockReset();
    apiMocks.updateAgentRunningConfig.mockReset();
    apiMocks.updateAgentLanguage.mockReset();
    apiMocks.updateUserTimezone.mockReset();
    messageMock.success.mockReset();
    messageMock.warning.mockReset();
    messageMock.error.mockReset();
    modalConfirmMock.mockReset();

    apiMocks.getAgentRunningConfigAccess.mockResolvedValue({
      agent_id: "agent-1",
      access_role: "owner",
      can_view: true,
      can_edit: true,
      is_governance: false,
      visibility: "private",
      owner_user_id: "owner-1",
    });
    apiMocks.getAgentRunningConfigSummary.mockResolvedValue({
      agent_id: "agent-1",
      name: "Shared Agent",
      language: "zh",
      timezone: "Asia/Shanghai",
      active_model: { provider_id: "provider-1", model: "model-1" },
      model_switchable: true,
      access_role: "user",
      can_edit: false,
      read_only_reason: "仅使用权限",
    });
    apiMocks.getAgentRunningConfig.mockResolvedValue(makeConfig());
    apiMocks.getAgentRunningConfigVersion.mockResolvedValue({ version: 4 });
    apiMocks.getAgentRunningConfigRuntimeStatus.mockResolvedValue({
      state: "applied",
    });
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

  it("loads only the safe summary for a read-only user", async () => {
    apiMocks.getAgentRunningConfigAccess.mockResolvedValue({
      agent_id: "agent-1",
      access_role: "user",
      can_view: true,
      can_edit: false,
      is_governance: false,
      visibility: "public",
      owner_user_id: "owner-1",
    });
    const { result } = renderConfigHook();

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.isReadOnly).toBe(true);
    expect(result.current.readOnlySummary?.name).toBe("Shared Agent");
    expect(apiMocks.getAgentRunningConfigSummary).toHaveBeenCalledTimes(1);
    expect(apiMocks.getAgentRunningConfig).not.toHaveBeenCalled();
    expect(apiMocks.getAgentRunningConfigVersion).not.toHaveBeenCalled();
    expect(apiMocks.getAgentLanguage).not.toHaveBeenCalled();
    expect(apiMocks.getUserTimezone).not.toHaveBeenCalled();
    expect(apiMocks.getAgentRunningConfigRuntimeStatus).not.toHaveBeenCalled();
  });

  it("loads editable config with the explicit server-verified governance context", async () => {
    apiMocks.getAgentRunningConfigAccess.mockResolvedValue({
      agent_id: "managed-agent",
      access_role: "admin_governance",
      can_view: true,
      can_edit: true,
      is_governance: true,
      visibility: "private",
      owner_user_id: "owner-2",
    });

    const { result } = renderConfigHook(undefined, "managed-agent");
    await waitFor(() => expect(result.current.loading).toBe(false));

    const governance = { agentId: "managed-agent", governance: true };
    expect(apiMocks.getAgentRunningConfigAccess).toHaveBeenCalledWith(
      governance,
    );
    expect(apiMocks.getAgentRunningConfig).toHaveBeenCalledWith(governance);
    expect(result.current.access?.is_governance).toBe(true);
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
    expect(apiMocks.updateAgentRunningConfig).toHaveBeenCalledWith(
      expect.any(Object),
      4,
    );
    expect(messageMock.success).toHaveBeenCalledWith("agentConfig.saveSuccess");
  });

  it("exposes pending reload after persistence and retries it", async () => {
    apiMocks.updateAgentRunningConfig.mockResolvedValue(makeConfig());
    apiMocks.getAgentRunningConfigRuntimeStatus
      .mockResolvedValueOnce({ state: "applied" })
      .mockResolvedValueOnce({ state: "pending_reload" });
    apiMocks.retryAgentRunningConfigReload.mockResolvedValue({
      state: "applied",
    });
    const { result } = renderConfigHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleSave();
    });

    expect(result.current.runtimeState).toBe("pending_reload");
    expect(messageMock.warning).toHaveBeenCalledWith(
      "agentConfig.savedPendingReload",
    );

    await act(async () => {
      await result.current.handleRetryReload();
    });

    expect(apiMocks.retryAgentRunningConfigReload).toHaveBeenCalledTimes(1);
    expect(result.current.runtimeState).toBe("applied");
  });

  it("keeps pending reload visible when a retry fails", async () => {
    apiMocks.getAgentRunningConfigRuntimeStatus.mockResolvedValue({
      state: "pending_reload",
    });
    apiMocks.retryAgentRunningConfigReload.mockRejectedValue(
      new Error("reload failed"),
    );
    const { result } = renderConfigHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleRetryReload();
    });

    expect(result.current.runtimeState).toBe("pending_reload");
    expect(messageMock.error).toHaveBeenCalledWith("reload failed");
  });

  it("shows a reload confirmation when the config version is stale", async () => {
    apiMocks.updateAgentRunningConfig.mockRejectedValue(
      new Error(
        'Configuration changed - {"detail":{"code":"config_version_conflict","current_version":5}}',
      ),
    );
    const { result } = renderConfigHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleSave();
    });

    expect(modalConfirmMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "agentConfig.versionConflictTitle",
        content: "agentConfig.versionConflictContent",
      }),
    );
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("refreshes into the read-only summary when edit access is revoked", async () => {
    apiMocks.updateAgentRunningConfig.mockRejectedValue(
      new Error('403 - {"detail":"forbidden"}'),
    );
    apiMocks.getAgentRunningConfigAccess
      .mockResolvedValueOnce({
        agent_id: "agent-1",
        access_role: "owner",
        can_view: true,
        can_edit: true,
        is_governance: false,
        visibility: "private",
      })
      .mockResolvedValueOnce({
        agent_id: "agent-1",
        access_role: "user",
        can_view: true,
        can_edit: false,
        is_governance: false,
        visibility: "public",
      });

    const { result } = renderConfigHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleSave();
    });

    await waitFor(() => expect(result.current.isReadOnly).toBe(true));
    expect(apiMocks.getAgentRunningConfigSummary).toHaveBeenCalledTimes(1);
    expect(apiMocks.getAgentRunningConfig).toHaveBeenCalledTimes(2);
    expect(messageMock.error).not.toHaveBeenCalled();
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

  it("handleSave rebases form values on the latest config so independent settings are preserved", async () => {
    const loadedConfig = makeConfig({
      coding_mode: { enabled: false },
      plan: { enabled: false },
    } as Partial<Config>);
    const latestConfig = makeConfig({
      coding_mode: { enabled: true },
      plan: { enabled: true },
    } as Partial<Config>);
    apiMocks.getAgentRunningConfig
      .mockResolvedValueOnce(loadedConfig)
      .mockResolvedValueOnce(latestConfig);
    mockGetFieldsValue.mockReturnValue({ shell_command_timeout: 90 });
    apiMocks.updateAgentRunningConfig.mockImplementation(
      async (config) => config,
    );

    const { result } = renderConfigHook();
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.handleSave();
    });

    const saved = apiMocks.updateAgentRunningConfig.mock
      .calls[0][0] as Config & {
      coding_mode: { enabled: boolean };
      plan: { enabled: boolean };
    };
    expect(saved.shell_command_timeout).toBe(90);
    expect(saved.coding_mode.enabled).toBe(true);
    expect(saved.plan.enabled).toBe(true);
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

  it("keeps the previous timezone and reports the backend error when saving fails", async () => {
    apiMocks.updateUserTimezone.mockRejectedValue(new Error("timezone failed"));
    const { result } = renderConfigHook();
    await waitFor(() => expect(result.current.timezone).toBe("UTC"));

    await act(async () => {
      await result.current.handleTimezoneChange("Asia/Shanghai");
    });

    expect(result.current.timezone).toBe("UTC");
    expect(messageMock.error).toHaveBeenCalledWith("timezone failed");
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

  it("keeps the previous language and reports the backend error when saving fails", async () => {
    apiMocks.updateAgentLanguage.mockRejectedValue(
      new Error("language failed"),
    );
    const { result } = renderConfigHook();
    await waitFor(() => expect(result.current.language).toBe("en"));

    act(() => result.current.handleLanguageChange("zh"));
    const options = modalConfirmMock.mock.calls[0][0] as {
      onOk: () => Promise<void>;
    };
    await act(async () => options.onOk());

    expect(result.current.language).toBe("en");
    expect(messageMock.error).toHaveBeenCalledWith("language failed");
  });
});
