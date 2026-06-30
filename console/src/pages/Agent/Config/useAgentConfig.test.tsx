import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { AgentsRunningConfig } from "../../../api/types";

// vi.hoisted runs before the hoisted vi.mock factories, so the shared mock
// objects are available inside them.
const hoisted = vi.hoisted(() => {
  const mockSetFieldsValue = vi.fn();
  const mockValidateFields = vi.fn();
  const mockFormInstance = {
    setFieldsValue: mockSetFieldsValue,
    validateFields: mockValidateFields,
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
  apiMocks,
  messageMock,
  modalConfirmMock,
} = hoisted;

type Config = AgentsRunningConfig;

function makeConfig(overrides: Partial<Config> = {}): Config {
  return {
    max_iters: 10,
    auto_continue_on_text_only: false,
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

function renderConfigHook() {
  return renderHook(() => useAgentConfig());
}

describe("useAgentConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSetFieldsValue.mockReset();
    mockValidateFields.mockReset();
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
});
