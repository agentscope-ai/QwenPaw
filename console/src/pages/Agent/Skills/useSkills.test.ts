import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { SkillSpec } from "../../../api/types";

// vi.hoisted runs before the hoisted vi.mock factories, so the shared mock
// objects are available inside them.
const hoisted = vi.hoisted(() => {
  const messageMock = {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  };
  const apiMocks = {
    listSkills: vi.fn(),
    refreshSkills: vi.fn(),
    createSkill: vi.fn(),
    uploadSkill: vi.fn(),
    startHubSkillInstall: vi.fn(),
    getHubSkillInstallStatus: vi.fn(),
    cancelHubSkillInstall: vi.fn(),
    enableSkill: vi.fn(),
    disableSkill: vi.fn(),
    deleteSkill: vi.fn(),
    getBlockedHistory: vi.fn(),
    getSkillScanner: vi.fn(),
  };
  const modalConfirmMock = vi.fn();
  const invalidateSkillCacheMock = vi.fn();
  const parseErrorDetailMock = vi.fn();
  const handleScanErrorMock = vi.fn().mockReturnValue(false);
  const checkScanWarningsMock = vi.fn().mockResolvedValue(undefined);
  const showScanErrorModalMock = vi.fn();
  // A stable translation function so useCallback dependencies don't change on
  // every render and trigger an infinite fetchSkills loop via useEffect.
  const stableT = (k: string) => k;
  return {
    messageMock,
    apiMocks,
    modalConfirmMock,
    invalidateSkillCacheMock,
    parseErrorDetailMock,
    handleScanErrorMock,
    checkScanWarningsMock,
    showScanErrorModalMock,
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
  return { __esModule: true, Modal };
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

vi.mock("../../../api/modules/skill", () => ({
  __esModule: true,
  invalidateSkillCache: hoisted.invalidateSkillCacheMock,
}));

vi.mock("../../../utils/error", () => ({
  __esModule: true,
  parseErrorDetail: hoisted.parseErrorDetailMock,
}));

vi.mock("../../../utils/scanError", () => ({
  __esModule: true,
  handleScanError: hoisted.handleScanErrorMock,
  checkScanWarnings: hoisted.checkScanWarningsMock,
  showScanErrorModal: hoisted.showScanErrorModalMock,
}));

import { useSkills } from "./useSkills";

const {
  apiMocks,
  messageMock,
  modalConfirmMock,
  parseErrorDetailMock,
  handleScanErrorMock,
} = hoisted;

function makeSkill(overrides: Partial<SkillSpec> = {}): SkillSpec {
  return {
    name: "my-skill",
    description: "test",
    content: "content",
    source: "local",
    enabled: true,
    ...overrides,
  };
}

function renderSkillsHook() {
  return renderHook(() => useSkills());
}

describe("useSkills", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkills.mockReset();
    apiMocks.refreshSkills.mockReset();
    apiMocks.createSkill.mockReset();
    apiMocks.uploadSkill.mockReset();
    apiMocks.startHubSkillInstall.mockReset();
    apiMocks.getHubSkillInstallStatus.mockReset();
    apiMocks.cancelHubSkillInstall.mockReset();
    apiMocks.enableSkill.mockReset();
    apiMocks.disableSkill.mockReset();
    apiMocks.deleteSkill.mockReset();
    apiMocks.getBlockedHistory.mockReset();
    apiMocks.getSkillScanner.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    messageMock.warning.mockReset();
    modalConfirmMock.mockReset();
    parseErrorDetailMock.mockReset();
    handleScanErrorMock.mockReset();
    handleScanErrorMock.mockReturnValue(false);

    apiMocks.listSkills.mockResolvedValue([makeSkill()]);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
  });

  it("fetchSkills success: sets skills list and loading true->false", async () => {
    const skills = [makeSkill({ name: "a" }), makeSkill({ name: "b" })];
    apiMocks.listSkills.mockResolvedValue(skills);
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.skills).toEqual(skills);
  });

  it("fetchSkills failure: message.error", async () => {
    apiMocks.listSkills.mockRejectedValue(new Error("boom"));
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(messageMock.error).toHaveBeenCalledWith("skills.loadFailed");
  });

  it("createSkill success: message.success + api.createSkill called + returns {success:true, name}", async () => {
    apiMocks.createSkill.mockResolvedValue({
      created: true,
      name: "new-skill",
    });
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean; name?: string } | undefined;
    await act(async () => {
      ret = await result.current.createSkill("new-skill", "content");
    });

    expect(apiMocks.createSkill).toHaveBeenCalledWith(
      "new-skill",
      "content",
      undefined,
      undefined,
    );
    expect(messageMock.success).toHaveBeenCalledWith(
      "skills.createdSuccessfully",
    );
    expect(ret).toEqual({ success: true, name: "new-skill" });
  });

  it("createSkill failure with suggested_name: returns {success:false, conflict}", async () => {
    const error = new Error("conflict");
    apiMocks.createSkill.mockRejectedValue(error);
    const detail = { suggested_name: "renamed-skill", conflict: true };
    parseErrorDetailMock.mockReturnValue(detail);
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean; conflict?: unknown } | undefined;
    await act(async () => {
      ret = await result.current.createSkill("dup", "content");
    });

    expect(ret).toEqual({ success: false, conflict: detail });
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("createSkill failure without suggested_name: handleError message.error + returns {success:false}", async () => {
    const error = new Error("save failed");
    apiMocks.createSkill.mockRejectedValue(error);
    parseErrorDetailMock.mockReturnValue(null);
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.createSkill("x", "content");
    });

    expect(ret).toEqual({ success: false });
    expect(messageMock.error).toHaveBeenCalledWith("save failed");
  });

  it("uploadSkill success count>0: message.success + fetchSkills", async () => {
    apiMocks.uploadSkill.mockResolvedValue({
      imported: ["a", "b"],
      count: 2,
      enabled: true,
    });
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    const listCallsBefore = apiMocks.listSkills.mock.calls.length;

    let ret: { success: boolean; imported?: string[] } | undefined;
    await act(async () => {
      ret = await result.current.uploadSkill(new File([], "x.zip"));
    });

    expect(ret).toEqual({ success: true, imported: ["a", "b"] });
    expect(messageMock.success).toHaveBeenCalled();
    expect(apiMocks.listSkills.mock.calls.length).toBeGreaterThan(
      listCallsBefore,
    );
  });

  it("uploadSkill success count=0: message.warning", async () => {
    apiMocks.uploadSkill.mockResolvedValue({
      imported: [],
      count: 0,
      enabled: true,
    });
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.uploadSkill(new File([], "x.zip"));
    });

    expect(messageMock.warning).toHaveBeenCalledWith("skills.uploadNoChange");
  });

  it("uploadSkill failure with conflicts array: returns {success:false, conflict}", async () => {
    const error = new Error("conflict");
    apiMocks.uploadSkill.mockRejectedValue(error);
    const detail = {
      conflicts: [{ skill_name: "a", suggested_name: "a-1", reason: "dup" }],
    };
    parseErrorDetailMock.mockReturnValue(detail);
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean; conflict?: unknown } | undefined;
    await act(async () => {
      ret = await result.current.uploadSkill(new File([], "x.zip"));
    });

    expect(ret).toEqual({ success: false, conflict: detail });
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("importFromHub empty input: message.warning(provideUrl) + returns {success:false}", async () => {
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("   ");
    });

    expect(ret).toEqual({ success: false });
    expect(messageMock.warning).toHaveBeenCalledWith("skills.provideUrl");
    expect(apiMocks.startHubSkillInstall).not.toHaveBeenCalled();
  });

  it("importFromHub non-http(s): message.warning(validUrl) + returns {success:false}", async () => {
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("ftp://example.com/x");
    });

    expect(ret).toEqual({ success: false });
    expect(messageMock.warning).toHaveBeenCalledWith("skills.validUrl");
    expect(apiMocks.startHubSkillInstall).not.toHaveBeenCalled();
  });

  it("importFromHub success: startHubSkillInstall + status completed -> message.success + {success:true, name}", async () => {
    apiMocks.startHubSkillInstall.mockResolvedValue({
      task_id: "task-1",
      bundle_url: "http://x",
      version: "1",
      enable: true,
      status: "pending",
      error: null,
      result: null,
      created_at: 0,
      updated_at: 0,
    });
    apiMocks.getHubSkillInstallStatus.mockResolvedValueOnce({
      task_id: "task-1",
      bundle_url: "http://x",
      version: "1",
      enable: true,
      status: "completed",
      error: null,
      result: { installed: true, name: "imported-skill" },
      created_at: 0,
      updated_at: 0,
    });
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean; name?: string } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("http://example.com/x");
    });

    expect(apiMocks.startHubSkillInstall).toHaveBeenCalledWith({
      bundle_url: "http://example.com/x",
      enable: true,
      target_name: undefined,
    });
    expect(messageMock.success).toHaveBeenCalled();
    expect(ret).toEqual({ success: true, name: "imported-skill" });
  });

  it("importFromHub status failed with conflicts: returns {success:false, conflict}", async () => {
    apiMocks.startHubSkillInstall.mockResolvedValue({
      task_id: "task-1",
      bundle_url: "http://x",
      version: "1",
      enable: true,
      status: "pending",
      error: null,
      result: null,
      created_at: 0,
      updated_at: 0,
    });
    const conflictResult = {
      conflicts: [{ skill_name: "a", suggested_name: "a-1" }],
    };
    apiMocks.getHubSkillInstallStatus.mockResolvedValueOnce({
      task_id: "task-1",
      bundle_url: "http://x",
      version: "1",
      enable: true,
      status: "failed",
      error: "conflict",
      result: conflictResult,
      created_at: 0,
      updated_at: 0,
    });
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret: { success: boolean; conflict?: unknown } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("http://example.com/x");
    });

    expect(ret).toEqual({ success: false, conflict: conflictResult });
  });

  it("toggleEnabled disabling an enabled skill: disableSkill + enabled:false + message.success", async () => {
    apiMocks.disableSkill.mockResolvedValue(undefined);
    const skill = makeSkill({ name: "s1", enabled: true });
    apiMocks.listSkills.mockResolvedValue([skill]);
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.skills.some((s) => s.name === "s1")).toBe(true);
    });

    let ok = false;
    await act(async () => {
      ok = await result.current.toggleEnabled(skill);
    });

    expect(apiMocks.disableSkill).toHaveBeenCalledWith("s1");
    expect(messageMock.success).toHaveBeenCalledWith(
      "skills.disabledSuccessfully",
    );
    expect(ok).toBe(true);
    const disabled = result.current.skills.find((s) => s.name === "s1");
    expect(disabled?.enabled).toBe(false);
  });

  it("toggleEnabled enabling a disabled skill: enableSkill + enabled:true + message.success", async () => {
    apiMocks.enableSkill.mockResolvedValue(undefined);
    apiMocks.listSkills.mockResolvedValue([
      makeSkill({ name: "s2", enabled: false }),
    ]);
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ok = false;
    await act(async () => {
      ok = await result.current.toggleEnabled(
        makeSkill({ name: "s2", enabled: false }),
      );
    });

    expect(apiMocks.enableSkill).toHaveBeenCalledWith("s2");
    expect(messageMock.success).toHaveBeenCalledWith(
      "skills.enabledSuccessfully",
    );
    expect(ok).toBe(true);
  });

  it("deleteSkill: Modal.confirm onOk + api.deleteSkill returned deleted:true -> message.success + returns true", async () => {
    apiMocks.deleteSkill.mockResolvedValue({ deleted: true });
    // Capture confirm options and invoke onOk synchronously.
    modalConfirmMock.mockImplementation((options: { onOk: () => void }) => {
      options.onOk();
    });
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret = false;
    await act(async () => {
      ret = await result.current.deleteSkill(makeSkill({ name: "to-delete" }));
    });

    expect(modalConfirmMock).toHaveBeenCalledTimes(1);
    expect(apiMocks.deleteSkill).toHaveBeenCalledWith("to-delete");
    expect(messageMock.success).toHaveBeenCalledWith("skills.deleteSuccess");
    expect(ret).toBe(true);
  });

  it("deleteSkill: Modal.confirm onCancel -> returns false and does not call api.deleteSkill", async () => {
    modalConfirmMock.mockImplementation((options: { onCancel: () => void }) => {
      options.onCancel();
    });
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let ret = true;
    await act(async () => {
      ret = await result.current.deleteSkill(makeSkill({ name: "keep" }));
    });

    expect(apiMocks.deleteSkill).not.toHaveBeenCalled();
    expect(ret).toBe(false);
  });
});
