import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ToolInfo } from "../../../api/modules/tools";

const harness = vi.hoisted(() => ({
  selectedAgent: "agent-a",
  listTools: vi.fn(),
  toggleTool: vi.fn(),
  updateAsyncExecution: vi.fn(),
  updateToolConfig: vi.fn(),
  getToolConfig: vi.fn(),
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  t: (key: string, fallback?: unknown) =>
    typeof fallback === "string" ? fallback : key,
}));

vi.mock("../../../api", () => ({
  default: {
    listTools: harness.listTools,
    toggleTool: harness.toggleTool,
    updateAsyncExecution: harness.updateAsyncExecution,
    updateToolConfig: harness.updateToolConfig,
    getToolConfig: harness.getToolConfig,
  },
}));

vi.mock("../../../stores/agentStore", () => {
  const useAgentStore = Object.assign(
    () => ({ selectedAgent: harness.selectedAgent }),
    { getState: () => ({ selectedAgent: harness.selectedAgent }) },
  );
  return { useAgentStore };
});

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: harness.message }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: harness.t }),
}));

import ToolsPage from "./index";

const POPULATED: ToolInfo[] = [
  {
    name: "plugin_tool",
    description: "Persisted plugin tool",
    enabled: true,
    async_execution: false,
    icon: "wrench",
    source_plugin_id: "plugin-a",
  },
];

describe("ToolsPage load recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    harness.selectedAgent = "agent-a";
    harness.toggleTool.mockResolvedValue(POPULATED[0]);
    harness.updateAsyncExecution.mockResolvedValue(POPULATED[0]);
    harness.updateToolConfig.mockResolvedValue({ status: "ok" });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    { label: "empty", recoveredTools: [] as ToolInfo[] },
    { label: "populated", recoveredTools: POPULATED },
  ])(
    "blocks mutations until Retry restores a real $label result",
    async ({ recoveredTools }) => {
      vi.spyOn(console, "error").mockImplementation(() => {});
      let loadFails = true;
      harness.listTools.mockImplementation(async () => {
        if (loadFails) throw new Error("network down");
        return recoveredTools;
      });

      render(<ToolsPage />);

      const retry = await screen.findByRole("button", {
        name: "common.retry",
      });
      expect(screen.getByRole("alert")).toHaveTextContent("tools.loadError");
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(screen.queryByRole("switch")).toBeNull();
      expect(harness.toggleTool).not.toHaveBeenCalled();
      expect(harness.updateAsyncExecution).not.toHaveBeenCalled();
      expect(harness.updateToolConfig).not.toHaveBeenCalled();

      loadFails = false;
      fireEvent.click(retry);

      if (recoveredTools.length === 0) {
        expect(await screen.findByRole("status")).toHaveTextContent(
          "tools.emptyState",
        );
        expect(screen.queryByRole("switch")).toBeNull();
      } else {
        expect(
          await screen.findByRole("switch", {
            name: "common.disable plugin_tool",
          }),
        ).toBeChecked();
      }
      expect(harness.listTools).toHaveBeenCalledTimes(2);
      expect(harness.listTools).toHaveBeenNthCalledWith(1, "agent-a");
      expect(harness.listTools).toHaveBeenNthCalledWith(2, "agent-a");
      expect(harness.toggleTool).not.toHaveBeenCalled();
      expect(harness.updateAsyncExecution).not.toHaveBeenCalled();
      expect(harness.updateToolConfig).not.toHaveBeenCalled();
    },
  );
});
