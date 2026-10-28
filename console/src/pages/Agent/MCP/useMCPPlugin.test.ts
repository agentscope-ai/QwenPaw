import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useMCPPlugin, type MCPPluginState } from "./useMCPPlugin";

const state = vi.hoisted(() => ({
  request: vi.fn(),
  reload: vi.fn(),
  agent: { selectedAgent: "one" },
}));
vi.mock("../../../api/request", () => ({ request: state.request }));
vi.mock("../../../plugins/usePluginLoader", () => ({
  reloadFrontendPlugin: state.reload,
}));
vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => state.agent,
}));

const absent: MCPPluginState = {
  id: "qwenpaw-mcp",
  installed: false,
  enabled: false,
  status: "not_installed",
  diagnostics: [],
};
const active: MCPPluginState = {
  ...absent,
  installed: true,
  enabled: true,
  status: "active",
};
const disabled: MCPPluginState = {
  ...active,
  enabled: false,
  status: "disabled",
};

beforeEach(() => {
  vi.clearAllMocks();
  state.request.mockReset();
  state.reload.mockReset().mockResolvedValue(undefined);
  state.agent.selectedAgent = "one";
});

it("entry reads state without installing, enabling, or fetching a plugin bundle", async () => {
  state.request.mockResolvedValue(absent);
  const { result } = renderHook(() => useMCPPlugin(false));
  await waitFor(() => expect(result.current.state).toEqual(absent));
  expect(state.request.mock.calls).toEqual([
    ["/mcp-plugin", { signal: expect.any(AbortSignal) }],
  ]);
  expect(state.reload).not.toHaveBeenCalled();
});

it.each([absent, disabled])(
  "explicit activation preserves the existing $status flow",
  async (initial) => {
    state.request.mockImplementation(async (_path, options) =>
      options?.method ? active : initial,
    );
    const { result } = renderHook(() => useMCPPlugin(false));
    await waitFor(() => expect(result.current.state).toEqual(initial));
    state.request.mockImplementation(async () => active);
    await act(async () => result.current.activate());
    await waitFor(() => expect(result.current.state).toEqual(active));
    if (initial.installed) {
      expect(state.request).toHaveBeenCalledWith(
        "/plugins/qwenpaw-mcp/enabled",
        { method: "POST", body: JSON.stringify({ enabled: true }) },
      );
    } else {
      expect(state.request).toHaveBeenCalledWith("/mcp-plugin/install", {
        method: "POST",
      });
    }
    expect(state.reload).toHaveBeenCalledOnce();
  },
);

it("failed install can be retried with an explicit action", async () => {
  state.request.mockResolvedValue(absent);
  const { result } = renderHook(() => useMCPPlugin(false));
  await waitFor(() => expect(result.current.state).toEqual(absent));
  state.request.mockRejectedValueOnce(
    new Error("offline resource unavailable"),
  );
  await act(async () => result.current.activate());
  expect(result.current.error).toContain("offline resource unavailable");
  expect(result.current.busy).toBe(false);
  state.request.mockResolvedValue(active);
  await act(async () => result.current.activate());
  await waitFor(() => expect(result.current.state).toEqual(active));
  expect(result.current.error).toBe("");
});

it("uninstall notification returns the retained shell to initial state", async () => {
  state.request.mockResolvedValue(active);
  const { result } = renderHook(() => useMCPPlugin(true));
  await waitFor(() => expect(result.current.state).toEqual(active));
  state.request.mockResolvedValue(absent);
  act(() => window.dispatchEvent(new Event("qwenpaw:mcp-plugin-changed")));
  await waitFor(() => expect(result.current.state).toEqual(absent));
  expect(state.reload).not.toHaveBeenCalled();
});

it("aborts old workspace state reads and ignores a response after cancellation", async () => {
  let resolve!: (value: MCPPluginState) => void;
  state.request
    .mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    )
    .mockResolvedValueOnce(disabled);
  const { result, rerender } = renderHook(() => useMCPPlugin(false));
  const firstSignal = state.request.mock.calls[0][1].signal as AbortSignal;
  state.agent.selectedAgent = "two";
  rerender();
  expect(firstSignal.aborted).toBe(true);
  await waitFor(() => expect(result.current.state).toEqual(disabled));
  await act(async () => resolve(active));
  expect(result.current.state).toEqual(disabled);
  expect(state.reload).not.toHaveBeenCalled();
});
