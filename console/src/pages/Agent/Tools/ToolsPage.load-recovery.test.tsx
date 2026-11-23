import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ToolInfo } from "../../../api/modules/tools";

const harness = vi.hoisted(() => ({
  selectedAgent: "agent-a",
  listTools: vi.fn(),
  toggleTool: vi.fn(),
  updateAsyncExecution: vi.fn(),
  updateToolConfig: vi.fn(),
  getToolConfig: vi.fn(),
  message: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    destroy: vi.fn(),
  },
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
    {
      getState: () => ({ selectedAgent: harness.selectedAgent }),
      subscribe: () => () => {},
    },
  );
  return { useAgentStore };
});

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: harness.message }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: harness.t }),
}));

// Use the real antd form methods through Vitest's module interop.
vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const { Form, Input, Select } = await import("antd");
  return { ...(await importOriginal<object>()), Form, Input, Select };
});

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

const configurableTool: ToolInfo = {
  ...POPULATED[0],
  requires_config: true,
  config_fields: [
    { name: "api_key", label: "API Key", type: "password", required: true },
  ],
};

async function openPluginConfig() {
  render(<ToolsPage />);
  const configure = await screen.findByRole("button", {
    name: "tools.configure plugin_tool",
  });
  await act(async () => {
    fireEvent.click(configure);
  });
  return screen.getByLabelText("API Key");
}

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

  it("keeps the password form open while refreshing tools after a save", async () => {
    let finishRefresh!: (tools: ToolInfo[]) => void;
    const refresh = new Promise<ToolInfo[]>((resolve) => {
      finishRefresh = resolve;
    });
    harness.listTools
      .mockResolvedValueOnce([configurableTool])
      .mockReturnValueOnce(refresh);
    harness.getToolConfig.mockResolvedValue({ api_key: "***" });

    render(<ToolsPage />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "tools.configure plugin_tool",
      }),
    );
    const password = await screen.findByDisplayValue("***");
    vi.useFakeTimers();
    try {
      fireEvent.change(password, { target: { value: "new-key" } });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    } finally {
      vi.useRealTimers();
    }

    expect(harness.listTools).toHaveBeenCalledTimes(2);
    expect(harness.updateToolConfig).toHaveBeenCalledExactlyOnceWith(
      "plugin_tool",
      { api_key: "new-key" },
      "agent-a",
    );
    expect(screen.getByLabelText("API Key")).toBe(password);

    finishRefresh([{ ...configurableTool, config_values: { api_key: "***" } }]);
    await waitFor(() =>
      expect(
        screen.queryByText("tools.requiresConfig"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText("API Key")).toBe(password);
    expect(harness.getToolConfig).toHaveBeenCalledTimes(1);
  });

  it("closes after saving without waiting for the list refresh", async () => {
    let finishRefresh!: (tools: ToolInfo[]) => void;
    const refresh = new Promise<ToolInfo[]>((resolve) => {
      finishRefresh = resolve;
    });
    harness.listTools
      .mockResolvedValueOnce([configurableTool])
      .mockReturnValueOnce(refresh);
    harness.getToolConfig.mockResolvedValue({});

    const password = await openPluginConfig();
    fireEvent.change(password, { target: { value: "new-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(harness.listTools).toHaveBeenCalledTimes(2));
    expect(harness.updateToolConfig).toHaveBeenCalledExactlyOnceWith(
      "plugin_tool",
      { api_key: "new-key" },
      "agent-a",
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await act(async () => {
      finishRefresh([
        { ...configurableTool, config_values: { api_key: "***" } },
      ]);
    });
    expect(screen.queryByText("tools.requiresConfig")).toBeNull();
  });

  it("retries a failed refresh without resaving or losing the tool list", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const disabledTool = { ...configurableTool, enabled: false };
    const configured = { ...disabledTool, config_values: { api_key: "***" } };
    harness.listTools
      .mockResolvedValueOnce([disabledTool])
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce([configured]);
    harness.getToolConfig.mockResolvedValue({});
    harness.toggleTool.mockResolvedValue({ ...configured, enabled: true });

    const password = await openPluginConfig();
    fireEvent.change(password, { target: { value: "new-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    const retry = await screen.findByRole("button", { name: "common.retry" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("alert")).toHaveTextContent("tools.loadError");
    expect(screen.getByText("tools.requiresConfig")).toBeInTheDocument();
    expect(screen.getByRole("switch")).not.toBeChecked();
    fireEvent.click(retry);

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(screen.queryByText("tools.requiresConfig")).toBeNull();
    expect(harness.listTools).toHaveBeenNthCalledWith(3, "agent-a");
    expect(harness.updateToolConfig).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("switch", { name: "common.enable plugin_tool" }),
    );
    expect(harness.toggleTool).toHaveBeenCalledWith("plugin_tool");
    expect(await screen.findByRole("switch")).toBeChecked();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
