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
  const showScanWarnModalMock = vi.fn();
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
    showScanWarnModalMock,
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
  useAgentStore: Object.assign(() => hoisted.agentState, {
    getState: () => hoisted.agentState,
  }),
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
  showScanWarnModal: hoisted.showScanWarnModalMock,
}));

import { useSkills } from "./useSkills";
import { notifySkillChange } from "../../../utils/skillChangeEvents";

const {
  apiMocks,
  messageMock,
  modalConfirmMock,
  parseErrorDetailMock,
  handleScanErrorMock,
  checkScanWarningsMock,
  harnessMocks,
  agentState,
  showScanWarnModalMock,
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

function renderSkillsHook() {
  return renderHook(() => useSkills());
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
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
    checkScanWarningsMock.mockReset();
    checkScanWarningsMock.mockResolvedValue(undefined);
    harnessMocks.listSkills.mockReset();
    showScanWarnModalMock.mockReset();
    agentState.selectedAgent = "agent-1";
    agentState.agents = [{ id: "agent-1", backend: "qwenpaw" }];

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

  it("refreshes an already-mounted workspace after a market install", async () => {
    apiMocks.listSkills
      .mockResolvedValueOnce([makeSkill({ name: "existing" })])
      .mockResolvedValue([makeSkill({ name: "installed-from-market" })]);
    const { result } = renderSkillsHook();

    await waitFor(() =>
      expect(result.current.skills[0]?.name).toBe("existing"),
    );

    act(() => {
      notifySkillChange("agent-1");
    });

    await waitFor(() =>
      expect(result.current.skills[0]?.name).toBe("installed-from-market"),
    );
    expect(apiMocks.listSkills).toHaveBeenCalledTimes(2);
    expect(apiMocks.listSkills).toHaveBeenLastCalledWith("agent-1");
  });

  it("loads Provider Skills separately as read-only inventory", async () => {
    agentState.agents = [
      {
        id: "agent-1",
        backend: "qoder",
        backend_capabilities: {
          provider_skills_discovery: true,
        },
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
    });

    const { result } = renderSkillsHook();

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(harnessMocks.listSkills).toHaveBeenCalledWith("qoder");
    expect(result.current.providerSkills).toHaveLength(1);
    expect(result.current.providerSkills[0].read_only).toBe(true);
  });

  it("fetchSkills failure: message.error", async () => {
    apiMocks.listSkills.mockRejectedValue(new Error("boom"));
    const { result } = renderSkillsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(messageMock.error).toHaveBeenCalledWith("skills.loadFailed");
    expect(result.current.error).toEqual(new Error("boom"));
    expect(result.current.ready).toBe(false);
  });

  it.each([
    { label: "empty", recoveredSkills: [] as SkillSpec[] },
    { label: "populated", recoveredSkills: [makeSkill({ name: "saved" })] },
  ])("Retry recovers a real $label result", async ({ recoveredSkills }) => {
    apiMocks.listSkills
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce(recoveredSkills);
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderSkillsHook();
    await waitFor(() => expect(result.current.error).toBeTruthy());

    await act(async () => {
      await result.current.refreshSkills();
    });

    expect(result.current.error).toBeNull();
    expect(result.current.ready).toBe(true);
    expect(result.current.skills).toEqual(recoveredSkills);
  });

  it("keeps agent B skills when agent A resolves after B", async () => {
    const agentARequest = deferred<SkillSpec[]>();
    const agentBRequest = deferred<SkillSpec[]>();
    apiMocks.listSkills
      .mockReturnValueOnce(agentARequest.promise)
      .mockReturnValueOnce(agentBRequest.promise);
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];

    const { result, rerender } = renderSkillsHook();
    agentState.selectedAgent = "agent-2";
    rerender();
    const agentBSkills = [makeSkill({ name: "agent-b" })];
    await act(async () => {
      agentBRequest.resolve(agentBSkills);
      await agentBRequest.promise;
    });
    expect(result.current.skills).toEqual(agentBSkills);
    expect(result.current.ready).toBe(true);

    await act(async () => {
      agentARequest.resolve([makeSkill({ name: "agent-a" })]);
      await agentARequest.promise;
    });
    expect(result.current.skills).toEqual(agentBSkills);
    expect(result.current.error).toBeNull();
  });

  it("ignores an agent A rejection after agent B loads", async () => {
    const agentARequest = deferred<SkillSpec[]>();
    apiMocks.listSkills
      .mockReturnValueOnce(agentARequest.promise)
      .mockResolvedValueOnce([makeSkill({ name: "agent-b" })]);
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { result, rerender } = renderSkillsHook();
    agentState.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => {
      agentARequest.reject(new Error("late A failure"));
      await agentARequest.promise.catch(() => undefined);
    });

    expect(result.current.skills[0]?.name).toBe("agent-b");
    expect(result.current.error).toBeNull();
    expect(messageMock.error).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("does not expose agent A's load error after switching to agent B", async () => {
    const agentBRequest = deferred<SkillSpec[]>();
    apiMocks.listSkills
      .mockRejectedValueOnce(new Error("agent A failed"))
      .mockReturnValueOnce(agentBRequest.promise);
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result, rerender } = renderSkillsHook();
    await waitFor(() => expect(result.current.error).toBeTruthy());

    agentState.selectedAgent = "agent-2";
    rerender();

    expect(result.current.error).toBeNull();
    expect(result.current.ready).toBe(false);
    expect(apiMocks.listSkills).toHaveBeenNthCalledWith(1, "agent-1");
    expect(apiMocks.listSkills).toHaveBeenNthCalledWith(2, "agent-2");

    await act(async () => {
      agentBRequest.resolve([]);
      await agentBRequest.promise;
    });
  });

  it("blocks create until the current agent has loaded", async () => {
    const pendingLoad = deferred<SkillSpec[]>();
    apiMocks.listSkills.mockReturnValue(pendingLoad.promise);
    const { result } = renderSkillsHook();

    let response: { success: boolean } | undefined;
    await act(async () => {
      response = await result.current.createSkill("unsafe", "content");
    });

    expect(response).toEqual({ success: false });
    expect(apiMocks.createSkill).not.toHaveBeenCalled();
    await act(async () => {
      pendingLoad.resolve([]);
      await pendingLoad.promise;
    });
  });

  it("blocks stale agent A mutation callbacks after agent B loads", async () => {
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];
    apiMocks.listSkills.mockResolvedValue([]);
    const { result, rerender } = renderSkillsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));
    const staleAgentAMutations = {
      createSkill: result.current.createSkill,
      uploadSkill: result.current.uploadSkill,
      importFromHub: result.current.importFromHub,
      toggleEnabled: result.current.toggleEnabled,
      deleteSkill: result.current.deleteSkill,
    };

    agentState.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.clearAllMocks();

    await act(async () => {
      await staleAgentAMutations.createSkill("stale", "content");
      await staleAgentAMutations.uploadSkill(new File([], "stale.zip"));
      await staleAgentAMutations.importFromHub("https://example.com/stale");
      await staleAgentAMutations.toggleEnabled(makeSkill());
      await staleAgentAMutations.deleteSkill(makeSkill());
    });

    expect(apiMocks.createSkill).not.toHaveBeenCalled();
    expect(apiMocks.uploadSkill).not.toHaveBeenCalled();
    expect(apiMocks.startHubSkillInstall).not.toHaveBeenCalled();
    expect(apiMocks.enableSkill).not.toHaveBeenCalled();
    expect(apiMocks.disableSkill).not.toHaveBeenCalled();
    expect(apiMocks.deleteSkill).not.toHaveBeenCalled();
    expect(modalConfirmMock).not.toHaveBeenCalled();
  });

  it.each(["create", "upload", "toggle", "delete"] as const)(
    "does not publish a late agent A %s result into agent B",
    async (actionName) => {
      agentState.agents = [
        { id: "agent-1", backend: "qwenpaw" },
        { id: "agent-2", backend: "qwenpaw" },
      ];
      apiMocks.listSkills.mockResolvedValue([]);
      const operation = deferred<unknown>();
      if (actionName === "create") {
        apiMocks.createSkill.mockReturnValue(operation.promise);
      } else if (actionName === "upload") {
        apiMocks.uploadSkill.mockReturnValue(operation.promise);
      } else if (actionName === "toggle") {
        apiMocks.enableSkill.mockReturnValue(operation.promise);
      } else {
        apiMocks.deleteSkill.mockReturnValue(operation.promise);
        modalConfirmMock.mockImplementation((options: { onOk: () => void }) =>
          options.onOk(),
        );
      }
      const { result, rerender } = renderSkillsHook();
      await waitFor(() => expect(result.current.ready).toBe(true));

      let pending: Promise<unknown>;
      act(() => {
        if (actionName === "create") {
          pending = result.current.createSkill("same-name", "content");
        } else if (actionName === "upload") {
          pending = result.current.uploadSkill(new File([], "skill.zip"));
        } else if (actionName === "toggle") {
          pending = result.current.toggleEnabled(
            makeSkill({ name: "same-name", enabled: false }),
          );
        } else {
          pending = result.current.deleteSkill(
            makeSkill({ name: "same-name" }),
          );
        }
      });

      agentState.selectedAgent = "agent-2";
      rerender();
      await waitFor(() => expect(result.current.ready).toBe(true));
      vi.clearAllMocks();
      await act(async () => {
        if (actionName === "create") {
          operation.resolve({ created: true, name: "same-name" });
        } else if (actionName === "upload") {
          operation.resolve({ imported: ["same-name"], count: 1 });
        } else if (actionName === "delete") {
          operation.resolve({ deleted: true });
        } else {
          operation.resolve(undefined);
        }
        await pending!;
      });

      expect(messageMock.success).not.toHaveBeenCalled();
      expect(messageMock.error).not.toHaveBeenCalled();
      expect(result.current.uploading).toBe(false);
      expect(result.current.ready).toBe(true);
    },
  );

  it("does not publish a late agent A mutation rejection into agent B", async () => {
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];
    apiMocks.listSkills.mockResolvedValue([]);
    const operation = deferred<unknown>();
    apiMocks.uploadSkill.mockReturnValue(operation.promise);
    const { result, rerender } = renderSkillsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));

    let pending!: Promise<unknown>;
    act(() => {
      pending = result.current.uploadSkill(new File([], "skill.zip"));
    });
    agentState.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.clearAllMocks();
    await act(async () => {
      operation.reject(new Error("late A failure"));
      await pending;
    });

    expect(messageMock.error).not.toHaveBeenCalled();
    expect(result.current.uploading).toBe(false);
    expect(result.current.ready).toBe(true);
  });

  it.each([
    ["A to B", false],
    ["A to B to A", true],
  ] as const)(
    "does not show a stale scan warning after %s",
    async (_label, switchBackToA) => {
      agentState.agents = [
        { id: "agent-1", backend: "qwenpaw" },
        { id: "agent-2", backend: "qwenpaw" },
      ];
      apiMocks.listSkills.mockResolvedValue([]);
      apiMocks.createSkill.mockResolvedValue({
        created: true,
        name: "agent-a-skill",
      });
      const scan = deferred<void>();
      checkScanWarningsMock.mockImplementation(async (...args: unknown[]) => {
        await scan.promise;
        const shouldShow = args[4] as () => boolean;
        if (shouldShow()) showScanWarnModalMock();
      });
      const { result, rerender } = renderSkillsHook();
      await waitFor(() => expect(result.current.ready).toBe(true));

      let pending!: Promise<unknown>;
      act(() => {
        pending = result.current.createSkill("agent-a-skill", "content");
      });
      await waitFor(() =>
        expect(checkScanWarningsMock).toHaveBeenCalledTimes(1),
      );
      agentState.selectedAgent = "agent-2";
      rerender();
      await waitFor(() => expect(result.current.ready).toBe(true));
      if (switchBackToA) {
        agentState.selectedAgent = "agent-1";
        rerender();
        await waitFor(() => expect(result.current.ready).toBe(true));
      }

      await act(async () => {
        scan.resolve();
        await pending;
      });

      expect(showScanWarnModalMock).not.toHaveBeenCalled();
    },
  );

  it("shows a scan warning for the current agent mutation", async () => {
    agentState.selectedAgent = "agent-2";
    agentState.agents = [{ id: "agent-2", backend: "qwenpaw" }];
    apiMocks.listSkills.mockResolvedValue([]);
    apiMocks.createSkill.mockResolvedValue({
      created: true,
      name: "agent-b-skill",
    });
    checkScanWarningsMock.mockImplementation(async (...args: unknown[]) => {
      const shouldShow = args[4] as () => boolean;
      if (shouldShow()) showScanWarnModalMock();
    });
    const { result } = renderSkillsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));

    await act(async () => {
      await result.current.createSkill("agent-b-skill", "content");
    });

    expect(showScanWarnModalMock).toHaveBeenCalledTimes(1);
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
      "agent-1",
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

    expect(apiMocks.startHubSkillInstall).toHaveBeenCalledWith(
      {
        bundle_url: "http://example.com/x",
        enable: true,
        target_name: undefined,
      },
      "agent-1",
    );
    expect(apiMocks.getHubSkillInstallStatus).toHaveBeenCalledWith(
      "task-1",
      "agent-1",
    );
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

  it("does not poll agent B when agent A hub start resolves late", async () => {
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];
    apiMocks.listSkills.mockResolvedValue([]);
    const start = deferred<Record<string, unknown>>();
    apiMocks.startHubSkillInstall.mockReturnValue(start.promise);
    const { result, rerender } = renderSkillsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));

    let pending!: Promise<unknown>;
    act(() => {
      pending = result.current.importFromHub("https://example.com/a.zip");
    });
    agentState.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => {
      start.resolve({ task_id: "agent-a-task" });
      await pending;
    });

    expect(apiMocks.startHubSkillInstall).toHaveBeenCalledWith(
      expect.anything(),
      "agent-1",
    );
    expect(apiMocks.getHubSkillInstallStatus).not.toHaveBeenCalled();
    expect(result.current.importing).toBe(false);
  });

  it("keeps agent A hub polling and cancellation out of agent B", async () => {
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];
    apiMocks.listSkills.mockResolvedValue([]);
    apiMocks.startHubSkillInstall.mockResolvedValue({
      task_id: "agent-a-task",
    });
    const status = deferred<Record<string, unknown>>();
    apiMocks.getHubSkillInstallStatus.mockReturnValue(status.promise);
    apiMocks.cancelHubSkillInstall.mockResolvedValue(undefined);
    const { result, rerender } = renderSkillsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));

    let pending!: Promise<unknown>;
    act(() => {
      pending = result.current.importFromHub("https://example.com/a.zip");
    });
    await waitFor(() =>
      expect(apiMocks.getHubSkillInstallStatus).toHaveBeenCalledWith(
        "agent-a-task",
        "agent-1",
      ),
    );
    act(() => result.current.cancelImport());
    expect(apiMocks.cancelHubSkillInstall).toHaveBeenCalledWith(
      "agent-a-task",
      "agent-1",
    );

    agentState.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.clearAllMocks();
    await act(async () => {
      status.resolve({ status: "cancelled", result: null });
      await pending;
    });

    expect(messageMock.warning).not.toHaveBeenCalled();
    expect(apiMocks.cancelHubSkillInstall).not.toHaveBeenCalled();
    expect(result.current.importing).toBe(false);
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

    expect(apiMocks.disableSkill).toHaveBeenCalledWith("s1", "agent-1");
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

    expect(apiMocks.enableSkill).toHaveBeenCalledWith("s2", "agent-1");
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
    expect(apiMocks.deleteSkill).toHaveBeenCalledWith("to-delete", "agent-1");
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

  it("does not delete agent B from an agent A confirmation", async () => {
    agentState.agents = [
      { id: "agent-1", backend: "qwenpaw" },
      { id: "agent-2", backend: "qwenpaw" },
    ];
    let confirm: { onOk: () => void } | undefined;
    modalConfirmMock.mockImplementation((options) => {
      confirm = options as { onOk: () => void };
    });
    const { result, rerender } = renderSkillsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));

    let pending!: Promise<boolean>;
    act(() => {
      pending = result.current.deleteSkill(makeSkill({ name: "same-name" }));
    });
    await waitFor(() => expect(confirm).toBeDefined());

    agentState.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => confirm?.onOk());
    await act(async () => pending);

    expect(apiMocks.deleteSkill).not.toHaveBeenCalled();
  });
});
