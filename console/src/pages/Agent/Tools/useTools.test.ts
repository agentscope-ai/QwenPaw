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
  return { messageMock, apiMocks, stableT };
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
  });

  it("loadTools failure shows message.error('tools.loadError')", async () => {
    apiMocks.listTools.mockRejectedValue(new Error("boom"));

    const { result } = renderToolsHook();

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(messageMock.error).toHaveBeenCalledWith("tools.loadError");
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

  it("saveToolConfig success shows message.success('tools.configSaved')", async () => {
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

    expect(apiMocks.updateToolConfig).toHaveBeenCalledWith("a", {
      key: "value",
    });
    expect(messageMock.success).toHaveBeenCalledWith("tools.configSaved");
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
