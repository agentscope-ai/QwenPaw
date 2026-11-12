import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Grid } from "antd";
import {
  useLocation,
  useNavigate,
  useParams,
  type Location,
} from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installHostExternals } from "@/plugins/hostExternals";
import { useMenuItems, useRoutes } from "@/plugins/registry/hooks";
import { menuRegistry, routeRegistry } from "@/plugins/registry/store";
import { flattenMenu } from "@/layouts/registry/adapter";
import SettingsCenter from "@/pages/SettingsCenter";
import { renderWithProviders } from "@/test/common_setup";
import { useSessionListStore } from "@/stores/sessionListStore";
import { useSessionAttentionStore } from "@/stores/sessionAttentionStore";
import sessionApi from "@/pages/Chat/sessionApi";
import MainLayout from ".";

vi.mock("../Sidebar", () => ({
  default: function Sidebar() {
    const location = useLocation();
    const navigate = useNavigate();
    const menu = useMenuItems("primary.agentScoped");
    const routes = useRoutes();
    return (
      <aside>
        Session sidebar
        <button
          onClick={() =>
            navigate("/settings/general", {
              state: {
                settingsReturnTo:
                  location.pathname + location.search + location.hash,
              },
            })
          }
        >
          Open settings
        </button>
        {flattenMenu(menu, routes, 16).map((entry) => (
          <button key={entry.key} onClick={() => navigate(entry.path)}>
            {entry.label}
          </button>
        ))}
      </aside>
    );
  },
}));
vi.mock("../AmbientLight", () => ({ default: () => null }));
vi.mock("../Header", () => ({ default: () => null }));
vi.mock("@/components/ConsolePollService", () => ({ default: () => null }));
vi.mock("@/components/AgentStatusPollingController", () => ({
  AgentStatusPollingController: () => null,
}));
vi.mock("@/stores/useSyncCodingMode", () => ({
  useSyncCodingMode: () => undefined,
}));
vi.mock("@/plugins/PluginContext", () => ({
  usePlugins: () => ({ loading: false }),
}));
vi.mock("@/pages/SettingsCenter/GeneralSettings", () => ({
  default: () => <div>General settings</div>,
}));

function PluginPage() {
  const { section } = useParams();
  const navigate = useNavigate();
  return (
    <div>
      <div>Plugin configuration{section ? `: ${section}` : ""}</div>
      <button onClick={() => navigate("?tab=advanced#field")}>
        Change plugin tab
      </button>
      <button
        onClick={() =>
          navigate("?tab=replaced#field", {
            replace: true,
            state: { tabValue: "kept" },
          })
        }
      >
        Replace plugin tab
      </button>
      <button onClick={() => navigate("/settings/example-child")}>
        Open settings child
      </button>
      <button
        onClick={() =>
          navigate("/example-details/advanced?tab=extra#field", {
            state: { pluginValue: "kept" },
          })
        }
      >
        Open plugin child
      </button>
    </div>
  );
}

function HistoryControls() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">
        {location.pathname + location.search + location.hash}
      </output>
      <output data-testid="location-state">
        {JSON.stringify(location.state)}
      </output>
      <button onClick={() => navigate(-1)}>History back</button>
      <button onClick={() => navigate(1)}>History forward</button>
      <button onClick={() => navigate("/other-plugin")}>Other plugin</button>
      <button onClick={() => navigate("/my-plugin")}>Open plugin route</button>
    </>
  );
}

function renderLayout(path: string | Partial<Location> = "/settings/general") {
  return renderWithProviders(
    <>
      <HistoryControls />
      <MainLayout />
    </>,
    { initialEntries: [path] },
  );
}

function registerSettingsPlugin(path: string, withMeta = true) {
  window.QwenPaw.route!.add("example", {
    id: "example.settings",
    path,
    component: PluginPage,
    ...(withMeta && {
      meta: {
        domain: "settings" as const,
        title: "Example settings",
        scope: "global" as const,
        layout: "standard" as const,
        navigation: "settings" as const,
      },
    }),
  });
  window.QwenPaw.menu!.add("example", {
    id: "example.settings.menu",
    label: "Example extension",
    location: "primary.settings",
    parentId: withMeta ? "core.settings-group" : "plugins-group",
    route: "example.settings",
  });
}

function registerSharedPlugin(withMeta = true) {
  registerSettingsPlugin("/my-plugin", withMeta);
  window.QwenPaw.menu!.add("example", {
    id: "example.chat.menu",
    label: "Example workspace",
    location: "primary.agentScoped",
    route: "example.settings",
  });
}

beforeEach(() => {
  useSessionListStore.setState({ sessions: [] });
  useSessionAttentionStore.setState({ seenFinishedAt: {} });
  vi.spyOn(sessionApi, "getSessionList").mockImplementation(
    async () => useSessionListStore.getState().sessions,
  );
  vi.spyOn(Grid, "useBreakpoint").mockReturnValue({ md: true });
  menuRegistry.__resetForTests();
  routeRegistry.__resetForTests();
  Reflect.deleteProperty(window, "QwenPaw");
  installHostExternals();
  routeRegistry.addBuiltin([
    {
      id: "core.settings-center",
      path: "/settings/*",
      component: SettingsCenter,
    },
    {
      id: "core.models",
      path: "/models",
      component: () => <div>Model settings</div>,
    },
    {
      id: "core.chat",
      path: "/chat/*",
      component: () => <div>Chat page</div>,
    },
  ]);
  menuRegistry.addBuiltin([
    {
      id: "core.settings-group",
      location: "primary.settings",
      label: "Settings",
      isGroup: true,
    },
    {
      id: "plugins-group",
      location: "primary.settings",
      label: "Plugins",
      isGroup: true,
    },
  ]);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("browser document titles", () => {
  it("refreshes background completions without mounting a sidebar session list", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const visibility = vi
      .spyOn(document, "visibilityState", "get")
      .mockReturnValue("visible");
    const initial = {
      id: "chat-a",
      name: "Project plan",
      messages: [],
      lastFinishedAt: null,
    };
    useSessionListStore.setState({ sessions: [initial] });
    const list = vi.mocked(sessionApi.getSessionList);
    list.mockResolvedValue([initial]);
    renderLayout("/chat/chat-a");
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(document.title).toBe("Project plan · QwenPaw");

    hidden.mockReturnValue(true);
    visibility.mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    const completed = {
      ...initial,
      lastFinishedAt: "2026-11-09T10:00:00Z",
    };
    list.mockResolvedValue([completed]);
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(document.title).toBe("• Project plan · QwenPaw");
    expect(list).toHaveBeenCalledTimes(2);

    hidden.mockReturnValue(false);
    visibility.mockReturnValue("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(document.title).toBe("Project plan · QwenPaw");
    expect(list).toHaveBeenCalledTimes(3);
  });

  it("follows the current chat name and restores route titles after navigation", async () => {
    useSessionListStore.setState({
      sessions: [{ id: "chat a", name: "Project plan", messages: [] }],
    });
    renderLayout("/chat/chat%20a");
    expect(document.title).toBe("Project plan · QwenPaw");
    await act(async () => {});

    act(() => {
      useSessionListStore.setState({
        sessions: [{ id: "chat a", name: "Release notes", messages: [] }],
      });
    });
    expect(document.title).toBe("Release notes · QwenPaw");

    await userEvent.click(
      screen.getByRole("button", { name: "Open settings" }),
    );
    expect(document.title).toBe("Settings · QwenPaw");

    await userEvent.click(screen.getByRole("button", { name: "History back" }));
    expect(document.title).toBe("Release notes · QwenPaw");
  });

  it.each(["/chat", "/chat/new", "/chat/missing"])(
    "uses the default chat title at %s",
    (path) => {
      useSessionListStore.setState({
        sessions: [{ id: "chat-a", name: "Previous chat", messages: [] }],
      });
      renderLayout(path);
      expect(document.title).toBe("Chat · QwenPaw");
    },
  );
});

describe("plugin settings navigation", () => {
  it.each([true, false])(
    "uses the entry sidebar for a shared route with metadata %s and restores history",
    async (withMeta) => {
      registerSharedPlugin(withMeta);
      renderLayout("/chat");
      await userEvent.click(
        screen.getByRole("button", { name: "Example workspace" }),
      );
      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.getByText("Session sidebar")).toBeVisible();

      await userEvent.click(
        screen.getByRole("button", { name: "Open settings" }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Example extension" }),
      );
      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Example extension" }),
      ).toHaveAttribute("aria-current", "page");

      await userEvent.click(
        screen.getByRole("button", { name: "Back to app" }),
      );
      expect(screen.getByTestId("location")).toHaveTextContent("/my-plugin");
      expect(screen.getByText("Session sidebar")).toBeVisible();

      await userEvent.click(
        screen.getByRole("button", { name: "History back" }),
      );
      expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
      await userEvent.click(
        screen.getByRole("button", { name: "History back" }),
      );
      expect(screen.getByText("General settings")).toBeVisible();
      await userEvent.click(
        screen.getByRole("button", { name: "History back" }),
      );
      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.getByText("Session sidebar")).toBeVisible();

      await userEvent.click(
        screen.getByRole("button", { name: "History forward" }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: "History forward" }),
      );
      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    },
  );

  it("uses the app layout for shared direct links without a settings origin", () => {
    registerSharedPlugin();
    renderLayout("/my-plugin");
    expect(screen.getByText("Plugin configuration")).toBeVisible();
    expect(screen.getByText("Session sidebar")).toBeVisible();
  });

  it("retains the origin through replace navigation and remounting", async () => {
    registerSharedPlugin();
    const view = renderLayout();
    await userEvent.click(
      screen.getByRole("button", { name: "Example extension" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Replace plugin tab" }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/my-plugin?tab=replaced#field",
    );
    expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    const state = JSON.parse(screen.getByTestId("location-state").textContent!);
    expect(state.tabValue).toBe("kept");
    await userEvent.click(screen.getByRole("button", { name: "History back" }));
    expect(screen.getByText("General settings")).toBeVisible();
    view.unmount();

    renderLayout({
      pathname: "/my-plugin",
      search: "?tab=replaced",
      hash: "#field",
      state,
    });
    expect(screen.getByText("Plugin configuration")).toBeVisible();
    expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Example extension" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("renders a separately registered child under /settings without redirecting", async () => {
    registerSharedPlugin(false);
    window.QwenPaw.route!.add("example", {
      id: "example.child",
      path: "/settings/example-child",
      component: () => <div>Separate settings child</div>,
    });
    renderLayout();
    await userEvent.click(
      screen.getByRole("button", { name: "Example extension" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Open settings child" }),
    );
    expect(screen.getByText("Separate settings child")).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings/example-child",
    );
    expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Example extension" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("preserves settings across query, hash and separate same-plugin child routes", async () => {
    registerSharedPlugin();
    window.QwenPaw.route!.add("example", {
      id: "example.details",
      path: "/example-details/:section",
      component: () => <div>Plugin child configuration</div>,
    });
    window.QwenPaw.route!.add("other", {
      id: "other.workspace",
      path: "/other-plugin",
      component: () => <div>Other plugin workspace</div>,
    });
    renderLayout("/chat?session=1#messages");
    await userEvent.click(
      screen.getByRole("button", { name: "Open settings" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Example extension" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Change plugin tab" }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/my-plugin?tab=advanced#field",
    );
    expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Open plugin child" }),
    );
    expect(screen.getByText("Plugin child configuration")).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/example-details/advanced?tab=extra#field",
    );
    expect(screen.getByTestId("location-state")).toHaveTextContent(
      '"pluginValue":"kept"',
    );
    expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Example extension" }),
    ).toHaveAttribute("aria-current", "page");

    await userEvent.click(screen.getByRole("button", { name: "Other plugin" }));
    expect(screen.getByText("Other plugin workspace")).toBeVisible();
    expect(screen.getByText("Session sidebar")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "History back" }));
    expect(screen.getByText("Plugin child configuration")).toBeVisible();
    expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "History forward" }),
    );
    expect(screen.getByText("Session sidebar")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Open plugin route" }),
    );
    expect(screen.getByText("Plugin configuration")).toBeVisible();
    expect(screen.getByText("Session sidebar")).toBeVisible();
  });

  it("keeps the original app return URL after a separate child route", async () => {
    registerSettingsPlugin("/my-plugin");
    window.QwenPaw.route!.add("example", {
      id: "example.details",
      path: "/example-details/:section",
      component: () => <div>Plugin child configuration</div>,
    });
    renderLayout("/chat?session=1#messages");
    await userEvent.click(
      screen.getByRole("button", { name: "Open settings" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Example extension" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Open plugin child" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Back to app" }));
    expect(screen.getByText("Chat page")).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/chat?session=1#messages",
    );
    expect(screen.getByText("Session sidebar")).toBeVisible();
  });

  it.each(["/settings/myplugin", "/my-plugin"])(
    "keeps the settings navigation when opening %s and using history",
    async (path) => {
      registerSettingsPlugin(path);
      renderLayout();

      await userEvent.click(
        screen.getByRole("button", { name: "Example extension" }),
      );

      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.getByTestId("location")).toHaveTextContent(path);
      expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Example extension" }),
      ).toHaveAttribute("aria-current", "page");

      await userEvent.click(
        screen.getByRole("button", { name: "History back" }),
      );
      expect(screen.getByText("General settings")).toBeVisible();
      await userEvent.click(
        screen.getByRole("button", { name: "History forward" }),
      );
      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Models" }));
      expect(screen.getByText("Model settings")).toBeVisible();
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/settings/models",
      );

      await userEvent.click(
        screen.getByRole("button", { name: "Back to app" }),
      );
      expect(screen.getByText("Chat page")).toBeVisible();
      expect(screen.getByText("Session sidebar")).toBeVisible();
    },
  );

  it.each(["/settings/myplugin", "/my-plugin"])(
    "renders a direct link to %s without route metadata in the settings layout",
    (path) => {
      registerSettingsPlugin(path, false);
      renderLayout(path);

      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Example extension" }),
      ).toHaveAttribute("aria-current", "page");
    },
  );

  it("preserves route params, query strings and hashes on direct links", () => {
    registerSettingsPlugin("/settings/myplugin/:section");
    renderLayout("/settings/myplugin/details?tab=advanced#field");

    expect(screen.getByText("Plugin configuration: details")).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings/myplugin/details?tab=advanced#field",
    );
    expect(
      screen.getByRole("button", { name: "Example extension" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it.each([undefined, "Legacy settings"])(
    "keeps legacy registerRoutes pages in settings with title %s",
    (title) => {
      window.QwenPaw.registerRoutes!("legacy-example", [
        {
          path: "/legacy-settings",
          component: PluginPage,
          label: "Legacy extension",
          title,
        },
      ]);
      renderLayout("/legacy-settings");

      expect(screen.getByText("Plugin configuration")).toBeVisible();
      expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Legacy extension" }),
      ).toHaveAttribute("aria-current", "page");
    },
  );

  it("keeps the app sidebar for plugin routes outside the settings menu", () => {
    window.QwenPaw.route!.add("example", {
      id: "example.workspace",
      path: "/settings/workspace",
      component: PluginPage,
    });
    window.QwenPaw.menu!.add("example", {
      id: "example.workspace.menu",
      location: "primary.agentScoped",
      label: "Example workspace",
      route: "example.workspace",
    });
    renderLayout("/settings/workspace");

    expect(screen.getByText("Plugin configuration")).toBeVisible();
    expect(screen.getByText("Session sidebar")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Back to app" }),
    ).not.toBeInTheDocument();
  });

  it("opens settings plugins registered after the layout mounts", async () => {
    renderLayout();
    act(() => registerSettingsPlugin("/late-settings"));
    await userEvent.click(
      screen.getByRole("button", { name: "Example extension" }),
    );

    expect(screen.getByText("Plugin configuration")).toBeVisible();
    expect(screen.queryByText("Session sidebar")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Example extension" }),
    ).toHaveAttribute("aria-current", "page");
  });
});
