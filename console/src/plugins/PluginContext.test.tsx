// @vitest-environment jsdom
import { act, render, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/authStore";
import { PluginProvider, usePlugins } from "./PluginContext";
import { loadAllPlugins } from "./usePluginLoader";
import { resetLoadedPlugins } from "./usePluginLoader";

vi.mock("./usePluginLoader", () => ({
  loadAllPlugins: vi.fn(),
  resetLoadedPlugins: vi.fn(),
  watchPluginAccess: () => () => {},
}));

vi.mock("./pluginSystem", () => ({
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

it("does not delay authentication with a plugin request in the initial legacy placeholder mode", () => {
  useAuthStore.setState({ mode: "legacy", phase: "loading", user: null });
  render(
    <PluginProvider>
      <div>auth loading</div>
    </PluginProvider>,
  );
  expect(loadAllPlugins).not.toHaveBeenCalled();
});

it("does not briefly mount business pages before the plugin load begins", async () => {
  vi.mocked(loadAllPlugins).mockReturnValue(new Promise(() => {}));
  const mounted = vi.fn();
  function BusinessPage() {
    useEffect(() => {
      mounted();
    }, []);
    return <span>business</span>;
  }
  function Gate() {
    const phase = useAuthStore((state) => state.phase);
    const { loading } = usePlugins();
    return phase === "authenticated" && !loading ? <BusinessPage /> : null;
  }
  render(
    <PluginProvider>
      <Gate />
    </PluginProvider>,
  );
  act(() => {
    useAuthStore.setState({
      phase: "authenticated",
      user: {
        id: "a",
        username: "a",
        platform_role: "member",
        status: "active",
      },
    });
  });
  expect(mounted).not.toHaveBeenCalled();
});

it("does not let an old user's late completion release the new user's startup", async () => {
  let completeFirst!: (result: { loaded: number; failed: string[] }) => void;
  vi.mocked(loadAllPlugins)
    .mockReturnValueOnce(
      new Promise((resolve) => {
        completeFirst = resolve;
      }),
    )
    .mockReturnValueOnce(new Promise(() => {}));
  function State() {
    return <span>{usePlugins().loading ? "waiting" : "ready"}</span>;
  }
  const view = render(
    <PluginProvider>
      <State />
    </PluginProvider>,
  );
  act(() => {
    useAuthStore.setState({
      phase: "authenticated",
      user: {
        id: "a",
        username: "a",
        platform_role: "member",
        status: "active",
      },
    });
  });
  act(() => {
    useAuthStore.setState({
      user: {
        id: "b",
        username: "b",
        platform_role: "member",
        status: "active",
      },
    });
  });
  await act(async () => {
    completeFirst({ loaded: 0, failed: [] });
  });
  expect(view.getByText("waiting")).toBeInTheDocument();
  expect(vi.mocked(loadAllPlugins).mock.calls[0][0]?.aborted).toBe(true);
});
