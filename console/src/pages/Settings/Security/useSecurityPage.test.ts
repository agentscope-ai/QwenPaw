import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";

const hoisted = vi.hoisted(() => {
  const mockFormValidateFields = vi.fn();
  const mockFormResetFields = vi.fn();
  const mockFormSetFieldsValue = vi.fn();
  // useSecurityPage calls Form.useForm() twice (form + editForm). Use a single
  // shared instance for simplicity; per-call behavior is controlled via the
  // validateFields/resetFields/setFieldsValue fns below.
  const mockFormInstance = {
    validateFields: mockFormValidateFields,
    resetFields: mockFormResetFields,
    setFieldsValue: mockFormSetFieldsValue,
  };
  const messageMock = {
    success: vi.fn(),
    error: vi.fn(),
  };
  const apiMocks = {
    getToolGuard: vi.fn(),
    getBuiltinRules: vi.fn(),
    updateToolGuard: vi.fn(),
    updateSandbox: vi.fn(),
  };
  const stableT = (k: string) => k;
  const buildSaveBodyMock = vi.fn(() => ({
    disabled_rules: new Set(["r1"]),
    auto_denied_rules: [],
    shell_evasion_checks: {},
  }));
  const setEnabledMock = vi.fn();
  const fetchAllMock = vi.fn();
  return {
    mockFormInstance,
    mockFormValidateFields,
    mockFormResetFields,
    mockFormSetFieldsValue,
    messageMock,
    apiMocks,
    stableT,
    buildSaveBodyMock,
    setEnabledMock,
    fetchAllMock,
  };
});

vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  const passThrough = ({ children, ...props }: Record<string, unknown>) =>
    React.createElement("div", props, children as React.ReactNode);
  const Form = Object.assign(passThrough, {
    Item: passThrough,
    useForm: () => [hoisted.mockFormInstance],
  });
  return { __esModule: true, Form };
});

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: hoisted.stableT }),
}));

vi.mock("./useToolGuard", () => ({
  __esModule: true,
  useToolGuard: () => ({
    config: null,
    customRules: [],
    builtinRules: [],
    enabled: true,
    setEnabled: hoisted.setEnabledMock,
    sandboxEnabled: true,
    setSandboxEnabled: vi.fn(),
    mergedRules: [],
    shellEvasionChecks: {},
    toggleShellEvasionCheck: vi.fn(),
    loading: false,
    error: null,
    fetchAll: hoisted.fetchAllMock,
    toggleRule: vi.fn(),
    toggleAutoDeny: vi.fn(),
    deleteCustomRule: vi.fn(),
    addCustomRule: vi.fn(),
    updateCustomRule: vi.fn(),
    buildSaveBody: hoisted.buildSaveBodyMock,
  }),
}));

import { useSecurityPage } from "./useSecurityPage";

const {
  mockFormValidateFields,
  mockFormResetFields,
  mockFormSetFieldsValue,
  messageMock,
  apiMocks,
  fetchAllMock,
} = hoisted;

describe("useSecurityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFormValidateFields.mockReset();
    mockFormResetFields.mockReset();
    mockFormSetFieldsValue.mockReset();
    fetchAllMock.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    apiMocks.updateToolGuard.mockReset();
    apiMocks.updateSandbox.mockReset();
    apiMocks.updateSandbox.mockResolvedValue({ enabled: true });
    hoisted.buildSaveBodyMock.mockClear();
    hoisted.setEnabledMock.mockClear();
  });

  it("handleSave calls api.updateToolGuard with guarded_tools array and message.success", async () => {
    mockFormValidateFields.mockResolvedValue({
      enabled: true,
      guarded_tools: ["t1"],
      denied_tools: [],
    });
    apiMocks.updateToolGuard.mockResolvedValue({});

    const { result } = renderHook(() => useSecurityPage());

    await act(async () => {
      await result.current.handleSave();
    });

    expect(apiMocks.updateToolGuard).toHaveBeenCalledTimes(1);
    const body = apiMocks.updateToolGuard.mock.calls[0][0];
    expect(body.enabled).toBe(true);
    expect(body.guarded_tools).toEqual(["t1"]);
    expect(body.denied_tools).toEqual([]);
    expect(body.disabled_rules).toEqual(["r1"]);
    expect(body.auto_denied_rules).toEqual([]);
    expect(messageMock.success).toHaveBeenCalledWith("security.saveSuccess");
    expect(hoisted.setEnabledMock).toHaveBeenCalledWith(true);
  });

  it("handleSave sets guarded_tools to null when guardedTools is empty", async () => {
    mockFormValidateFields.mockResolvedValue({
      enabled: true,
      guarded_tools: [],
      denied_tools: ["d1"],
    });
    apiMocks.updateToolGuard.mockResolvedValue({});

    const { result } = renderHook(() => useSecurityPage());

    await act(async () => {
      await result.current.handleSave();
    });

    expect(apiMocks.updateToolGuard).toHaveBeenCalledTimes(1);
    const body = apiMocks.updateToolGuard.mock.calls[0][0];
    expect(body.guarded_tools).toBeNull();
    expect(body.denied_tools).toEqual(["d1"]);
  });

  it("handleSave silently returns on validation errorFields without api call or message.error", async () => {
    const validationErr = Object.assign(new Error("validate failed"), {
      errorFields: [{ name: ["enabled"], errors: ["required"] }],
    });
    mockFormValidateFields.mockRejectedValue(validationErr);

    const { result } = renderHook(() => useSecurityPage());

    await act(async () => {
      await result.current.handleSave();
    });

    expect(apiMocks.updateToolGuard).not.toHaveBeenCalled();
    expect(messageMock.error).not.toHaveBeenCalled();
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("handleSave calls message.error on other errors", async () => {
    mockFormValidateFields.mockResolvedValue({
      enabled: true,
      guarded_tools: ["t1"],
      denied_tools: [],
    });
    apiMocks.updateToolGuard.mockRejectedValue(new Error("server exploded"));

    const { result } = renderHook(() => useSecurityPage());

    await act(async () => {
      await result.current.handleSave();
    });

    expect(apiMocks.updateToolGuard).toHaveBeenCalledTimes(1);
    expect(messageMock.error).toHaveBeenCalledWith("server exploded");
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("handleReset calls form.resetFields and fetchAll", () => {
    const { result } = renderHook(() => useSecurityPage());

    act(() => {
      result.current.handleReset();
    });

    expect(mockFormResetFields).toHaveBeenCalledTimes(1);
    expect(fetchAllMock).toHaveBeenCalledTimes(1);
  });

  it("openAddRule sets editingRule null, edits form, and opens modal", () => {
    const { result } = renderHook(() => useSecurityPage());

    expect(result.current.editModal).toBe(false);

    act(() => {
      result.current.openAddRule();
    });

    expect(result.current.editModal).toBe(true);
    expect(result.current.editingRule).toBeNull();
    // editForm shares mockFormInstance in this mock.
    expect(mockFormResetFields).toHaveBeenCalledTimes(1);
    expect(mockFormSetFieldsValue).toHaveBeenCalledTimes(1);
    const setArg = mockFormSetFieldsValue.mock.calls[0][0];
    expect(setArg.severity).toBe("HIGH");
    expect(setArg.category).toBe("command_injection");
    expect(setArg.patterns).toBe("");
  });
});
