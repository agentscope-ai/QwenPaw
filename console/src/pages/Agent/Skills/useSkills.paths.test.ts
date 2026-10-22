import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
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
  const harnessMocks = {
    listSkills: vi.fn(),
  };
  const agentState = {
    selectedAgent: "agent-1",
    agents: [{ id: "agent-1", backend: "qwenpaw" }] as Array<
      Record<string, unknown>
    >,
  };
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
    harnessMocks,
    agentState,
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
  useAgentStore: () => hoisted.agentState,
}));

vi.mock("../../../api/modules/harness", () => ({
  harnessApi: hoisted.harnessMocks,
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
import { notifySkillChange } from "../../../utils/skillChangeEvents";

const {
  apiMocks,
  messageMock,
  modalConfirmMock,
  invalidateSkillCacheMock,
  parseErrorDetailMock,
  handleScanErrorMock,
  checkScanWarningsMock,
  showScanErrorModalMock,
  harnessMocks,
  agentState,
} = hoisted;

function makeSkill(overrides: Partial<SkillSpec> = {}): SkillSpec {
  return {
    name: "my-skill",
    description: "test",
    source: "local",
    enabled: true,
    ...overrides,
  };
}

// The hub install task shape returned by both startHubSkillInstall and
// getHubSkillInstallStatus. Only status/result/error vary across cases.
function hubTask(status: string, result: unknown, error: string | null = null) {
  return {
    task_id: "task-1",
    bundle_url: "http://x",
    version: "1",
    enable: true,
    status,
    error,
    result,
    created_at: 0,
    updated_at: 0,
  };
}

function renderSkillsHook() {
  return renderHook(() => useSkills());
}

async function renderIdle() {
  const view = renderSkillsHook();
  await waitFor(() => {
    expect(view.result.current.loading).toBe(false);
  });
  return view;
}

// Flush the pending microtasks of an already-started importFromHub call so the
// hook state and the task id ref catch up with the mocked api.
async function flushMicrotasks(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await Promise.resolve();
  }
}

describe("useSkills hardRefresh and provider discovery paths", () => {
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
    checkScanWarningsMock.mockReset();
    checkScanWarningsMock.mockResolvedValue(undefined);
    showScanErrorModalMock.mockReset();
    harnessMocks.listSkills.mockReset();
    invalidateSkillCacheMock.mockReset();
    agentState.selectedAgent = "agent-1";
    agentState.agents = [{ id: "agent-1", backend: "qwenpaw" }];

    apiMocks.listSkills.mockResolvedValue([makeSkill()]);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hardRefresh: invalidates the cache and replaces the list from refreshSkills", async () => {
    apiMocks.refreshSkills.mockResolvedValue([makeSkill({ name: "fresh" })]);
    const { result } = await renderIdle();

    await act(async () => {
      await result.current.hardRefresh();
    });

    expect(invalidateSkillCacheMock).toHaveBeenCalledWith({
      agentId: "agent-1",
    });
    expect(apiMocks.refreshSkills).toHaveBeenCalledWith("agent-1");
    expect(result.current.skills.map((s) => s.name)).toEqual(["fresh"]);
    expect(result.current.loading).toBe(false);
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("hardRefresh: falls back to an empty list when refreshSkills resolves null", async () => {
    apiMocks.refreshSkills.mockResolvedValue(null);
    const { result } = await renderIdle();

    await act(async () => {
      await result.current.hardRefresh();
    });

    expect(result.current.skills).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it("hardRefresh failure: reports refreshFailed and still clears loading", async () => {
    apiMocks.refreshSkills.mockRejectedValue(new Error("refresh boom"));
    const { result } = await renderIdle();

    await act(async () => {
      await result.current.hardRefresh();
    });

    expect(messageMock.error).toHaveBeenCalledWith("skills.refreshFailed");
    expect(result.current.loading).toBe(false);
  });

  it("provider discovery: surfaces the backend warning message", async () => {
    agentState.agents = [
      {
        id: "agent-1",
        backend: "qoder",
        backend_capabilities: { provider_skills_discovery: true },
      },
    ];
    harnessMocks.listSkills.mockResolvedValue({
      skills: [
        {
          name: "find-skills",
          description: "Find Skills",
          provider_id: "qoder",
          source: "user",
          enabled: true,
          read_only: true,
          scope: "provider",
        },
      ],
      message: "partially available",
    });

    const { result } = await renderIdle();

    expect(harnessMocks.listSkills).toHaveBeenCalledWith("qoder");
    expect(messageMock.warning).toHaveBeenCalledWith("partially available");
    expect(result.current.providerSkills).toHaveLength(1);
  });

  it("provider discovery failure: keeps an empty inventory instead of throwing", async () => {
    agentState.agents = [
      {
        id: "agent-1",
        backend: "qoder",
        backend_capabilities: { provider_skills_discovery: true },
      },
    ];
    harnessMocks.listSkills.mockRejectedValue(new Error("discovery down"));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const { result } = await renderIdle();

    expect(warnSpy).toHaveBeenCalled();
    expect(result.current.providerSkills).toEqual([]);
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("fetchSkills: falls back to an empty list when the api resolves undefined", async () => {
    apiMocks.listSkills.mockResolvedValue(undefined);
    const { result } = await renderIdle();

    expect(result.current.skills).toEqual([]);
  });

  it("selected agent without a backend defaults to qwenpaw and skips discovery", async () => {
    agentState.agents = [{ id: "agent-1" }];
    const { result } = await renderIdle();

    expect(harnessMocks.listSkills).not.toHaveBeenCalled();
    expect(result.current.providerSkills).toEqual([]);
  });

  it("skill change events for another agent do not trigger a refetch", async () => {
    const { result } = await renderIdle();
    expect(apiMocks.listSkills).toHaveBeenCalledTimes(1);

    act(() => {
      notifySkillChange("some-other-agent");
    });
    await flushMicrotasks();

    expect(apiMocks.listSkills).toHaveBeenCalledTimes(1);
    expect(invalidateSkillCacheMock).toHaveBeenCalledTimes(1);
    expect(result.current.skills).toHaveLength(1);
  });
});

describe("useSkills error routing paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkills.mockReset();
    apiMocks.createSkill.mockReset();
    apiMocks.uploadSkill.mockReset();
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
    checkScanWarningsMock.mockReset();
    checkScanWarningsMock.mockResolvedValue(undefined);
    showScanErrorModalMock.mockReset();
    harnessMocks.listSkills.mockReset();
    agentState.selectedAgent = "agent-1";
    agentState.agents = [{ id: "agent-1", backend: "qwenpaw" }];

    apiMocks.listSkills.mockResolvedValue([makeSkill()]);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("createSkill: a security scan rejection is handled by the scan guard only", async () => {
    handleScanErrorMock.mockReturnValue(true);
    apiMocks.createSkill.mockRejectedValue(new Error("blocked by scanner"));

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.createSkill("s", "body");
    });

    expect(handleScanErrorMock).toHaveBeenCalled();
    expect(messageMock.error).not.toHaveBeenCalled();
    expect(ret).toEqual({ success: false });
  });

  it("createSkill: a non-Error payload falls back to the translated default message", async () => {
    apiMocks.createSkill.mockRejectedValue({ code: 500 });

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.createSkill("s", "body");
    });

    expect(messageMock.error).toHaveBeenCalledWith("skills.saveFailed");
    expect(ret).toEqual({ success: false });
  });

  it("uploadSkill failure without conflicts: routes through the generic error handler", async () => {
    apiMocks.uploadSkill.mockRejectedValue(new Error("upload boom"));
    parseErrorDetailMock.mockReturnValue({});

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.uploadSkill(new File([], "x.zip"));
    });

    expect(messageMock.error).toHaveBeenCalledWith("upload boom");
    expect(ret).toEqual({ success: false });
    expect(result.current.uploading).toBe(false);
  });

  it("uploadSkill: returns an empty imported list when the payload omits it", async () => {
    apiMocks.uploadSkill.mockResolvedValue({ count: 0 });

    const { result } = await renderIdle();
    let ret: { success: boolean; imported?: string[] } | undefined;
    await act(async () => {
      ret = await result.current.uploadSkill(new File([], "x.zip"));
    });

    expect(messageMock.warning).toHaveBeenCalledWith("skills.uploadNoChange");
    expect(ret).toEqual({ success: true, imported: [] });
  });

  it("toggleEnabled failure: reports the error message and returns false", async () => {
    apiMocks.disableSkill.mockRejectedValue(new Error("toggle boom"));
    const skill = makeSkill({ name: "s1", enabled: true });
    apiMocks.listSkills.mockResolvedValue([skill]);

    const { result } = await renderIdle();
    let ok = true;
    await act(async () => {
      ok = await result.current.toggleEnabled(skill);
    });

    expect(messageMock.error).toHaveBeenCalledWith("toggle boom");
    expect(ok).toBe(false);
  });

  it("toggleEnabled: leaves the other skills in the list untouched", async () => {
    apiMocks.disableSkill.mockResolvedValue(undefined);
    apiMocks.listSkills.mockResolvedValue([
      makeSkill({ name: "s1", enabled: true }),
      makeSkill({ name: "s2", enabled: true }),
    ]);

    const { result } = await renderIdle();
    await act(async () => {
      await result.current.toggleEnabled(
        makeSkill({ name: "s1", enabled: true }),
      );
    });

    expect(result.current.skills).toEqual([
      expect.objectContaining({ name: "s1", enabled: false }),
      expect.objectContaining({ name: "s2", enabled: true }),
    ]);
  });

  it("toggleEnabled enabling: leaves the other skills in the list untouched", async () => {
    apiMocks.enableSkill.mockResolvedValue(undefined);
    apiMocks.listSkills.mockResolvedValue([
      makeSkill({ name: "s1", enabled: false }),
      makeSkill({ name: "s2", enabled: false }),
    ]);

    const { result } = await renderIdle();
    await act(async () => {
      await result.current.toggleEnabled(
        makeSkill({ name: "s1", enabled: false }),
      );
    });

    expect(result.current.skills).toEqual([
      expect.objectContaining({ name: "s1", enabled: true }),
      expect.objectContaining({ name: "s2", enabled: false }),
    ]);
    expect(checkScanWarningsMock).toHaveBeenCalledWith(
      "s1",
      expect.anything(),
      expect.anything(),
      expect.anything(),
    );
  });

  it("deleteSkill: an api failure is logged and reported, returning false", async () => {
    modalConfirmMock.mockImplementation((options: { onOk: () => void }) => {
      options.onOk();
    });
    apiMocks.deleteSkill.mockRejectedValue(new Error("delete boom"));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { result } = await renderIdle();
    let ret = true;
    await act(async () => {
      ret = await result.current.deleteSkill(makeSkill({ name: "gone" }));
    });

    expect(errorSpy).toHaveBeenCalled();
    expect(messageMock.error).toHaveBeenCalledWith("skills.deleteFailed");
    expect(ret).toBe(false);
  });

  it("deleteSkill: a deleted:false payload returns false without a success toast", async () => {
    modalConfirmMock.mockImplementation((options: { onOk: () => void }) => {
      options.onOk();
    });
    apiMocks.deleteSkill.mockResolvedValue({ deleted: false });

    const { result } = await renderIdle();
    let ret = true;
    await act(async () => {
      ret = await result.current.deleteSkill(makeSkill({ name: "kept" }));
    });

    expect(apiMocks.deleteSkill).toHaveBeenCalledWith("kept");
    expect(messageMock.success).not.toHaveBeenCalled();
    expect(ret).toBe(false);
  });
});

describe("useSkills importFromHub polling paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkills.mockReset();
    apiMocks.startHubSkillInstall.mockReset();
    apiMocks.getHubSkillInstallStatus.mockReset();
    apiMocks.cancelHubSkillInstall.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    messageMock.warning.mockReset();
    parseErrorDetailMock.mockReset();
    handleScanErrorMock.mockReset();
    handleScanErrorMock.mockReturnValue(false);
    checkScanWarningsMock.mockReset();
    checkScanWarningsMock.mockResolvedValue(undefined);
    showScanErrorModalMock.mockReset();
    harnessMocks.listSkills.mockReset();
    agentState.selectedAgent = "agent-1";
    agentState.agents = [{ id: "agent-1", backend: "qwenpaw" }];

    apiMocks.listSkills.mockResolvedValue([makeSkill()]);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
    apiMocks.startHubSkillInstall.mockResolvedValue(hubTask("pending", null));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("importFromHub: an empty input string is normalised before validation", async () => {
    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("");
    });

    expect(messageMock.warning).toHaveBeenCalledWith("skills.provideUrl");
    expect(apiMocks.startHubSkillInstall).not.toHaveBeenCalled();
    expect(ret).toEqual({ success: false });
  });

  it("importFromHub: an empty task id exits the poll loop with success:false", async () => {
    apiMocks.startHubSkillInstall.mockResolvedValue(hubTask("pending", null));
    apiMocks.startHubSkillInstall.mockResolvedValueOnce({
      ...hubTask("pending", null),
      task_id: "",
    });

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(apiMocks.getHubSkillInstallStatus).not.toHaveBeenCalled();
    expect(result.current.importing).toBe(false);
    expect(ret).toEqual({ success: false });
  });

  it("importFromHub: a non-terminal status keeps polling until completion", async () => {
    let polls = 0;
    apiMocks.getHubSkillInstallStatus.mockImplementation(async () => {
      polls += 1;
      return polls === 1
        ? hubTask("running", null)
        : hubTask("completed", { installed: true, name: "late-skill" });
    });

    const { result } = await renderIdle();
    let ret: { success: boolean; name?: string } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(apiMocks.getHubSkillInstallStatus).toHaveBeenCalledTimes(2);
    expect(checkScanWarningsMock).toHaveBeenCalled();
    expect(ret).toEqual({ success: true, name: "late-skill" });
  }, 20000);

  it("importFromHub: completion without a name skips the scan warning check", async () => {
    apiMocks.getHubSkillInstallStatus.mockResolvedValue(
      hubTask("completed", { installed: true }),
    );

    const { result } = await renderIdle();
    let ret: { success: boolean; name?: string } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(checkScanWarningsMock).not.toHaveBeenCalled();
    expect(messageMock.success).toHaveBeenCalled();
    expect(ret).toEqual({ success: true, name: "" });
  });

  it("importFromHub: a security scan rejection opens the scan error modal", async () => {
    const scanResult = {
      type: "security_scan_failed",
      detail: "dangerous",
      skill_name: "bad-skill",
      max_severity: "high",
      findings: [],
    };
    apiMocks.getHubSkillInstallStatus.mockResolvedValue(
      hubTask("failed", scanResult, "scan"),
    );

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(showScanErrorModalMock).toHaveBeenCalledWith(
      scanResult,
      expect.anything(),
    );
    expect(messageMock.error).not.toHaveBeenCalled();
    expect(ret).toEqual({ success: false });
  });

  it("importFromHub: a plain failure throws the backend error into handleError", async () => {
    apiMocks.getHubSkillInstallStatus.mockResolvedValue(
      hubTask("failed", null, "backend said no"),
    );

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(showScanErrorModalMock).not.toHaveBeenCalled();
    expect(messageMock.error).toHaveBeenCalledWith("backend said no");
    expect(ret).toEqual({ success: false });
  });

  it("importFromHub: a failure without an error message uses the translated default", async () => {
    apiMocks.getHubSkillInstallStatus.mockResolvedValue(
      hubTask("failed", null, null),
    );

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(messageMock.error).toHaveBeenCalledWith("skills.importFailed");
    expect(ret).toEqual({ success: false });
  });

  it("importFromHub: start failure routes through handleError", async () => {
    apiMocks.startHubSkillInstall.mockRejectedValue(new Error("start boom"));

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(apiMocks.getHubSkillInstallStatus).not.toHaveBeenCalled();
    expect(messageMock.error).toHaveBeenCalledWith("start boom");
    expect(result.current.importing).toBe(false);
    expect(ret).toEqual({ success: false });
  });

  it("importFromHub: a cancelled task without a timeout reports importCancelled", async () => {
    apiMocks.getHubSkillInstallStatus.mockResolvedValue(
      hubTask("cancelled", null),
    );

    const { result } = await renderIdle();
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });

    expect(messageMock.warning).toHaveBeenCalledWith("skills.importCancelled");
    expect(apiMocks.cancelHubSkillInstall).not.toHaveBeenCalled();
    expect(ret).toEqual({ success: false });
  });

  it("importFromHub: exceeding the budget cancels the task and reports importTimeout", async () => {
    let polls = 0;
    apiMocks.getHubSkillInstallStatus.mockImplementation(async () => {
      polls += 1;
      return polls === 1
        ? hubTask("running", null)
        : hubTask("cancelled", null);
    });

    const { result } = await renderIdle();

    // The hook reads Date.now() once for startedAt and once per loop iteration
    // for the budget check, so only the first call keeps the real clock.
    const realNow = Date.now();
    let nowCalls = 0;
    const nowSpy = vi.spyOn(Date, "now").mockImplementation(() => {
      nowCalls += 1;
      return nowCalls === 1 ? realNow : realNow + 120000;
    });

    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await result.current.importFromHub("https://example.com/x");
    });
    nowSpy.mockRestore();

    expect(apiMocks.cancelHubSkillInstall).toHaveBeenCalledWith("task-1");
    expect(messageMock.warning).toHaveBeenCalledWith("skills.importTimeout");
    expect(ret).toEqual({ success: false });
  }, 20000);
});

describe("useSkills cancelImport paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSkills.mockReset();
    apiMocks.startHubSkillInstall.mockReset();
    apiMocks.getHubSkillInstallStatus.mockReset();
    apiMocks.cancelHubSkillInstall.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    messageMock.warning.mockReset();
    handleScanErrorMock.mockReset();
    handleScanErrorMock.mockReturnValue(false);
    harnessMocks.listSkills.mockReset();
    agentState.selectedAgent = "agent-1";
    agentState.agents = [{ id: "agent-1", backend: "qwenpaw" }];

    apiMocks.listSkills.mockResolvedValue([makeSkill()]);
    apiMocks.getBlockedHistory.mockResolvedValue([]);
    apiMocks.getSkillScanner.mockResolvedValue({});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("cancelImport: is a no-op while no import is running", async () => {
    const { result } = await renderIdle();

    act(() => {
      result.current.cancelImport();
    });

    expect(apiMocks.cancelHubSkillInstall).not.toHaveBeenCalled();
  });

  it("cancelImport: cancels the running task and records a manual reason", async () => {
    apiMocks.startHubSkillInstall.mockResolvedValue({
      ...hubTask("pending", null),
      task_id: "task-c",
    });
    let releaseStatus: (value: unknown) => void = () => {};
    apiMocks.getHubSkillInstallStatus.mockImplementation(
      () =>
        new Promise((resolve) => {
          releaseStatus = resolve;
        }),
    );

    const { result } = await renderIdle();
    let pending: Promise<{ success: boolean }> | undefined;
    await act(async () => {
      pending = result.current.importFromHub("https://example.com/x");
      await flushMicrotasks();
    });
    expect(result.current.importing).toBe(true);

    act(() => {
      result.current.cancelImport();
    });
    expect(apiMocks.cancelHubSkillInstall).toHaveBeenCalledWith("task-c");

    releaseStatus(hubTask("cancelled", null));
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await pending;
    });

    expect(messageMock.warning).toHaveBeenCalledWith("skills.importCancelled");
    expect(result.current.importing).toBe(false);
    expect(ret).toEqual({ success: false });
  });

  it("cancelImport: tolerates a start request that has not resolved yet", async () => {
    let releaseStart: (value: unknown) => void = () => {};
    apiMocks.startHubSkillInstall.mockImplementation(
      () =>
        new Promise((resolve) => {
          releaseStart = resolve;
        }),
    );

    const { result } = await renderIdle();
    let pending: Promise<{ success: boolean }> | undefined;
    await act(async () => {
      pending = result.current.importFromHub("https://example.com/x");
      await flushMicrotasks();
    });
    expect(result.current.importing).toBe(true);

    act(() => {
      result.current.cancelImport();
    });
    expect(apiMocks.cancelHubSkillInstall).not.toHaveBeenCalled();

    releaseStart({ ...hubTask("pending", null), task_id: "" });
    let ret: { success: boolean } | undefined;
    await act(async () => {
      ret = await pending;
    });

    expect(apiMocks.getHubSkillInstallStatus).not.toHaveBeenCalled();
    expect(ret).toEqual({ success: false });
  });
});
