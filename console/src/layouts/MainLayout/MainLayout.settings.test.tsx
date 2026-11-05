import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Grid } from "antd";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { installHostExternals } from "@/plugins/hostExternals";
import { menuRegistry, routeRegistry } from "@/plugins/registry/store";
import SettingsCenter from "@/pages/SettingsCenter";
import { renderWithProviders } from "@/test/common_setup";
import MainLayout from ".";

vi.mock("../Sidebar", () => ({
  default: () => <aside>Session sidebar</aside>,
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
  return <div>Plugin configuration{section ? `: ${section}` : ""}</div>;
}

function HistoryControls() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">
        {location.pathname + location.search + location.hash}
      </output>
      <button onClick={() => navigate(-1)}>History back</button>
      <button onClick={() => navigate(1)}>History forward</button>
    </>
  );
}

function renderLayout(path = "/settings/general") {
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

beforeEach(() => {
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
    { id: "core.chat", path: "/chat", component: () => <div>Chat page</div> },
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

describe("plugin settings navigation", () => {
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
