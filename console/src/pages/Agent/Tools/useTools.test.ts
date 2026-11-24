import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { ToolInfo } from "../../../api/modules/tools";

// vi.hoisted runs before the hoisted vi.mock factories, so the shared mock
// objects are available inside them. Stable t keeps useCallback deps stable and
// avoids an infinite loadTools loop via useEffect.
const hoisted = vi.hoisted(() => {
  const messageMock = {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  };
  const apiMocks = {
    listTools: vi.fn(),
    toggleTool: vi.fn(),
    updateAsyncExecution: vi.fn(),
    updateToolConfig: vi.fn(),
  };
  const stableT = (k: string) => k;
  return { messageMock, apiMocks, stableT, selectedAgent: "agent-1" };
});

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: Object.assign(
    () => ({ selectedAgent: hoisted.selectedAgent }),
    { getState: () => ({ selectedAgent: hoisted.selectedAgent }) },
  ),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: hoisted.messageMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: hoisted.stableT }),
}));

import { useTools } from "./useTools";

const { messageMock, apiMocks } = hoisted;

function makeTool(overrides: Partial<ToolInfo> = {}): ToolInfo {
  return {
    name: "tool-1",
    enabled: false,
    description: "test tool",
    async_execution: false,
    icon: "icon",
    ...overrides,
  };
}

function renderToolsHook() {
  return renderHook(() => useTools());
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("useTools", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listTools.mockReset();
    apiMocks.toggleTool.mockReset();
    apiMocks.updateAsyncExecution.mockReset();
    apiMocks.updateToolConfig.mockReset();
    messageMock.success.mockReset();
    messageMock.error.mockReset();
    messageMock.info.mockReset();
    hoisted.selectedAgent = "agent-1";

    apiMocks.listTools.mockResolvedValue([]);
  });

  it("mount calls listTools; tools populated and loading true then false", async () => {
    const tools = [makeTool({ name: "a", enabled: true })];
    apiMocks.listTools.mockResolvedValue(tools);

    const { result } = renderToolsHook();

    // Initial mount triggers loadTools; loading starts true.
    expect(result.current.loading).toBe(true);
    expect(apiMocks.listTools).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.tools).toEqual(tools);
    expect(result.current.error).toBeNull();
    expect(result.current.ready).toBe(true);
  });

  it("keeps the latest agent tools when an older request finishes last", async () => {
    const agentARequest = deferred<ToolInfo[]>();
    const agentBRequest = deferred<ToolInfo[]>();
    apiMocks.listTools
      .mockReturnValueOnce(agentARequest.promise)
      .mockReturnValueOnce(agentBRequest.promise);

    const { result, rerender } = renderToolsHook();
    expect(result.current.loading).toBe(true);

    hoisted.selectedAgent = "agent-2";
    rerender();
    expect(result.current.loading).toBe(true);

    const agentBTools = [makeTool({ name: "agent-b-tool" })];
    await act(async () => {
      agentBRequest.resolve(agentBTools);
      await agentBRequest.promise;
    });
    expect(result.current.tools).toEqual(agentBTools);
    expect(result.current.loading).toBe(false);

    await act(async () => {
      agentARequest.resolve([makeTool({ name: "agent-a-tool" })]);
      await agentARequest.promise;
    });
    expect(result.current.tools).toEqual(agentBTools);
    expect(result.current.loading).toBe(false);
    expect(apiMocks.listTools).toHaveBeenNthCalledWith(1, "agent-1");
    expect(apiMocks.listTools).toHaveBeenNthCalledWith(2, "agent-2");
  });

  it("keeps loading for the latest request and ignores work after unmount", async () => {
    const agentARequest = deferred<ToolInfo[]>();
    const agentBRequest = deferred<ToolInfo[]>();
    apiMocks.listTools
      .mockReturnValueOnce(agentARequest.promise)
      .mockReturnValueOnce(agentBRequest.promise);

    const { result, rerender, unmount } = renderToolsHook();
    hoisted.selectedAgent = "agent-2";
    rerender();

    await act(async () => {
      agentARequest.resolve([makeTool({ name: "agent-a-tool" })]);
      await agentARequest.promise;
    });
    expect(result.current.loading).toBe(true);
    expect(result.current.tools).toEqual([]);

    unmount();
    await act(async () => {
      agentBRequest.reject(new Error("settled after unmount"));
      await agentBRequest.promise.catch(() => undefined);
    });
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("ignores an older agent rejection after the new agent loads", async () => {
    const agentARequest = deferred<ToolInfo[]>();
    const agentBRequest = deferred<ToolInfo[]>();
    apiMocks.listTools
      .mockReturnValueOnce(agentARequest.promise)
      .mockReturnValueOnce(agentBRequest.promise);

    const { result, rerender } = renderToolsHook();
    hoisted.selectedAgent = "agent-2";
    rerender();
    const agentBTools = [makeTool({ name: "agent-b-tool" })];
    await act(async () => {
      agentBRequest.resolve(agentBTools);
      await agentBRequest.promise;
    });

    await act(async () => {
      agentARequest.reject(new Error("late agent-a failure"));
      await agentARequest.promise.catch(() => undefined);
    });

    expect(result.current.tools).toEqual(agentBTools);
    expect(result.current.error).toBeNull();
    expect(result.current.ready).toBe(true);
    expect(messageMock.error).not.toHaveBeenCalled();
  });

  it("ignores a stale load callback without invalidating the current load", async () => {
    const agentBRequest = deferred<ToolInfo[]>();
    apiMocks.listTools
      .mockResolvedValueOnce([makeTool({ name: "agent-a-tool" })])
      .mockReturnValueOnce(agentBRequest.promise);

    const { result, rerender } = renderToolsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));
    const staleAgentALoad = result.current.loadTools;

    hoisted.selectedAgent = "agent-2";
    rerender();
    await act(async () => {
      await staleAgentALoad();
    });
    expect(apiMocks.listTools).toHaveBeenCalledTimes(2);

    const agentBTools = [makeTool({ name: "agent-b-tool" })];
    await act(async () => {
      agentBRequest.resolve(agentBTools);
      await agentBRequest.promise;
    });
    expect(result.current.tools).toEqual(agentBTools);
    expect(result.current.ready).toBe(true);
  });

  it("loadTools failure shows message.error('tools.loadError')", async () => {
    apiMocks.listTools.mockRejectedValue(new Error("boom"));

    const { result } = renderToolsHook();

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(messageMock.error).toHaveBeenCalledWith("tools.loadError");
    expect(result.current.error).toEqual(new Error("boom"));
    expect(result.current.ready).toBe(false);
  });

  it("blocks list mutations when the loaded owner is not current", async () => {
    const enabled = makeTool({ name: "enabled", enabled: true });
    const disabled = makeTool({ name: "disabled", enabled: false });
    apiMocks.listTools.mockResolvedValue([enabled, disabled]);

    const { result } = renderToolsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));
    hoisted.selectedAgent = "agent-2";

    await act(async () => {
      await result.current.toggleEnabled(enabled);
      await result.current.toggleAsyncExecution(enabled);
      await result.current.enableAll();
      await result.current.disableAll();
    });

    expect(apiMocks.toggleTool).not.toHaveBeenCalled();
    expect(apiMocks.updateAsyncExecution).not.toHaveBeenCalled();
  });

  it("does not merge an old agent mutation into the new agent tools", async () => {
    const agentATool = makeTool({ name: "shared", enabled: false });
    const agentBTool = makeTool({ name: "shared", enabled: false });
    const oldToggle = deferred<ToolInfo>();
    apiMocks.listTools
      .mockResolvedValueOnce([agentATool])
      .mockResolvedValueOnce([agentBTool]);
    apiMocks.toggleTool.mockReturnValue(oldToggle.promise);

    const { result, rerender } = renderToolsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));
    let pendingToggle!: Promise<void>;
    act(() => {
      pendingToggle = result.current.toggleEnabled(result.current.tools[0]);
    });
    expect(result.current.tools[0].enabled).toBe(true);

    hoisted.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.tools[0].enabled).toBe(false);

    await act(async () => {
      oldToggle.resolve({ ...agentATool, enabled: true });
      await pendingToggle;
    });
    expect(result.current.tools[0]).toEqual(agentBTool);
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("releases an old batch lock when the new agent finishes loading", async () => {
    const agentATool = makeTool({ name: "agent-a-tool", enabled: false });
    const agentBTool = makeTool({ name: "agent-b-tool", enabled: false });
    const oldToggle = deferred<ToolInfo>();
    apiMocks.listTools
      .mockResolvedValueOnce([agentATool])
      .mockResolvedValueOnce([agentBTool]);
    apiMocks.toggleTool.mockReturnValue(oldToggle.promise);

    const { result, rerender } = renderToolsHook();
    await waitFor(() => expect(result.current.ready).toBe(true));
    let pendingBatch!: Promise<void>;
    act(() => {
      pendingBatch = result.current.enableAll();
    });
    expect(result.current.batchLoading).toBe(true);

    hoisted.selectedAgent = "agent-2";
    rerender();
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.batchLoading).toBe(false);

    await act(async () => {
      oldToggle.resolve({ ...agentATool, enabled: true });
      await pendingBatch;
    });
    expect(result.current.tools).toEqual([agentBTool]);
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("toggleEnabled success on disabled tool flips to enabled and shows enableSuccess", async () => {
    const tool = makeTool({ name: "a", enabled: false });
    apiMocks.listTools.mockResolvedValue([tool]);
    const toggled = { ...tool, enabled: true };
    apiMocks.toggleTool.mockResolvedValue(toggled);

    const { result } = renderToolsHook();
    await waitFor(() => {
      expect(result.current.tools).toHaveLength(1);
    });

    await act(async () => {
      await result.current.toggleEnabled(result.current.tools[0]);
    });

    expect(apiMocks.toggleTool).toHaveBeenCalledWith("a");
    expect(messageMock.success).toHaveBeenCalledWith("tools.enableSuccess");
    expect(result.current.tools[0].enabled).toBe(true);
  });

  it("toggleEnabled failure reverts optimistic update and shows toggleError", async () => {
    const tool = makeTool({ name: "a", enabled: false });
    apiMocks.listTools.mockResolvedValue([tool]);
    apiMocks.toggleTool.mockRejectedValue(new Error("fail"));

    const { result } = renderToolsHook();
    await waitFor(() => {
      expect(result.current.tools).toHaveLength(1);
    });

    await act(async () => {
      await result.current.toggleEnabled(result.current.tools[0]);
    });

    // After rollback the tool's enabled must return to its original value.
    expect(result.current.tools[0].enabled).toBe(false);
    expect(messageMock.error).toHaveBeenCalledWith("tools.toggleError");
  });

  it("toggleAsyncExecution success shows asyncExecutionEnabled and sets async_execution true", async () => {
    const tool = makeTool({ name: "a", async_execution: false });
    apiMocks.listTools.mockResolvedValue([tool]);
    const updated = { ...tool, async_execution: true };
    apiMocks.updateAsyncExecution.mockResolvedValue(updated);

    const { result } = renderToolsHook();
    await waitFor(() => {
      expect(result.current.tools).toHaveLength(1);
    });

    await act(async () => {
      await result.current.toggleAsyncExecution(result.current.tools[0]);
    });

    expect(apiMocks.updateAsyncExecution).toHaveBeenCalledWith("a", true);
    expect(messageMock.success).toHaveBeenCalledWith(
      "tools.asyncExecutionEnabled",
    );
    expect(result.current.tools[0].async_execution).toBe(true);
  });

  it("enableAll with no disabled tools shows info('tools.allEnabled') and skips toggleTool", async () => {
    const tool = makeTool({ name: "a", enabled: true });
    apiMocks.listTools.mockResolvedValue([tool]);

    const { result } = renderToolsHook();
    await waitFor(() => {
      expect(result.current.tools).toHaveLength(1);
    });

    await act(async () => {
      await result.current.enableAll();
    });

    expect(messageMock.info).toHaveBeenCalledWith("tools.allEnabled");
    expect(apiMocks.toggleTool).not.toHaveBeenCalled();
    expect(result.current.batchLoading).toBe(false);
  });

  it("enableAll with disabled tools calls Promise.all(toggleTool) and shows enableAllSuccess", async () => {
    const t1 = makeTool({ name: "a", enabled: false });
    const t2 = makeTool({ name: "b", enabled: false });
    apiMocks.listTools.mockResolvedValue([t1, t2]);
    apiMocks.toggleTool.mockImplementation(async (name: string) => ({
      ...makeTool({ name }),
      enabled: true,
    }));

    const { result } = renderToolsHook();
    await waitFor(() => {
      expect(result.current.tools).toHaveLength(2);
    });

    await act(async () => {
      await result.current.enableAll();
    });

    expect(apiMocks.toggleTool).toHaveBeenCalledTimes(2);
    expect(apiMocks.toggleTool).toHaveBeenCalledWith("a");
    expect(apiMocks.toggleTool).toHaveBeenCalledWith("b");
    expect(messageMock.success).toHaveBeenCalledWith("tools.enableAllSuccess");
    expect(result.current.tools.every((t) => t.enabled)).toBe(true);
  });

  it("saveToolConfig succeeds silently for autosave", async () => {
    apiMocks.updateToolConfig.mockResolvedValue({
      status: "ok",
      message: "saved",
    });

    const { result } = renderToolsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.saveToolConfig("a", { key: "value" });
    });

    expect(apiMocks.updateToolConfig).toHaveBeenCalledWith(
      "a",
      {
        key: "value",
      },
      "agent-1",
    );
    expect(messageMock.success).not.toHaveBeenCalled();
  });

  it("keeps an in-flight edit bound to its original agent", async () => {
    const { result, rerender } = renderToolsHook();
    const saveOriginal = result.current.saveToolConfig;
    let finishValidation!: () => void;
    const validation = new Promise<void>((resolve) => {
      finishValidation = resolve;
    });
    const pendingSave = (async () => {
      await validation;
      await saveOriginal("a", { key: "draft-a" });
    })();
    hoisted.selectedAgent = "agent-2";
    rerender();
    await act(async () => {
      finishValidation();
      await pendingSave;
    });
    expect(apiMocks.updateToolConfig).toHaveBeenLastCalledWith(
      "a",
      { key: "draft-a" },
      "agent-1",
    );
    await act(async () => {
      await result.current.saveToolConfig("a", { key: "draft-a" }, "agent-1");
    });
    expect(apiMocks.updateToolConfig).toHaveBeenLastCalledWith(
      "a",
      { key: "draft-a" },
      "agent-1",
    );
    hoisted.selectedAgent = "agent-1";
  });

  it("saveToolConfig failure shows message.error('tools.configSaveError') and rethrows", async () => {
    apiMocks.updateToolConfig.mockRejectedValue(new Error("save failed"));

    const { result } = renderToolsHook();
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await expect(
        result.current.saveToolConfig("a", { key: "value" }),
      ).rejects.toThrow("save failed");
    });

    expect(messageMock.error).toHaveBeenCalledWith("tools.configSaveError");
  });
});
