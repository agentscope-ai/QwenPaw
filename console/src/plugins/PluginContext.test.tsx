// @vitest-environment jsdom
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/authStore";
import { PluginProvider } from "./PluginContext";
import { loadAllPlugins } from "./usePluginLoader";
import { resetLoadedPlugins } from "./usePluginLoader";

vi.mock("./usePluginLoader", () => ({
  loadAllPlugins: vi.fn(),
  resetLoadedPlugins: vi.fn(),
}));

vi.mock("./hostExternals", () => ({
  pluginSystem: {
    getToolRenderConfig: () => ({}),
    subscribe: () => () => {},
  },
}));

vi.mock("./registry/store", () => ({
  routeRegistry: { snapshot: () => [] },
  subscribe: () => () => {},
}));

beforeEach(() => {
  vi.mocked(loadAllPlugins).mockReset();
  vi.mocked(resetLoadedPlugins).mockReset();
  vi.mocked(loadAllPlugins).mockResolvedValue({ loaded: 0, failed: [] });
  useAuthStore.setState({
    mode: "multi_user",
    phase: "anonymous",
    user: null,
  });
});

it("clears registrations before loading plugins for a different user", async () => {
  render(
    <PluginProvider>
      <div>child</div>
    </PluginProvider>,
  );
  act(() => {
    useAuthStore.setState({
      phase: "authenticated",
      user: {
        id: "member-1",
        username: "member-1",
        platform_role: "member",
        status: "active",
      },
    });
  });
  await waitFor(() => expect(loadAllPlugins).toHaveBeenCalledTimes(1));

  act(() => {
    useAuthStore.setState({
      phase: "authenticated",
      user: {
        id: "member-2",
        username: "member-2",
        platform_role: "member",
        status: "active",
      },
    });
  });

  await waitFor(() => expect(loadAllPlugins).toHaveBeenCalledTimes(2));
  expect(resetLoadedPlugins).toHaveBeenCalledTimes(3);
});

it("loads frontend plugins only after multi-user authentication", async () => {
  render(
    <PluginProvider>
      <div>child</div>
    </PluginProvider>,
  );

  expect(loadAllPlugins).not.toHaveBeenCalled();

  act(() => {
    useAuthStore.setState({
      phase: "authenticated",
      user: {
        id: "member-1",
        username: "member",
        platform_role: "member",
        status: "active",
      },
    });
  });

  await waitFor(() => expect(loadAllPlugins).toHaveBeenCalledTimes(1));
});
