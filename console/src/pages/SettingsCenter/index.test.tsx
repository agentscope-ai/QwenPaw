import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentType } from "react";
import { useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { ThemeProvider } from "@/contexts/ThemeContext";
import type { MenuItem } from "@/plugins/registry/types";
import {
  DEFAULT_FOCUS_ITEM_IDS,
  useSidebarModeStore,
} from "@/stores/sidebarModeStore";

const registry = vi.hoisted(() => ({
  routes: [] as Array<{
    id: string;
    path: string;
    Component: ComponentType;
  }>,
  settingsMenu: [] as MenuItem[],
}));

vi.mock("@/plugins/registry/hooks", () => ({
  useRoutes: () => registry.routes,
  useMenuItems: (location: string) =>
    location === "primary.settings" ? registry.settingsMenu : [],
}));

import SettingsCenter from ".";

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

describe("SettingsCenter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    registry.routes = [];
    registry.settingsMenu = [];
    localStorage.removeItem("qwenpaw_chat_wide_mode");
    localStorage.removeItem("qwenpaw-theme");
    useSidebarModeStore.setState({
      focusItemIds: DEFAULT_FOCUS_ITEM_IDS,
      hiddenPluginItemIds: [],
    });
  });

  it("uses the dark settings surface when dark theme is active", () => {
    localStorage.setItem("qwenpaw-theme", "dark");

    const { container } = renderWithProviders(
      <ThemeProvider>
        <SettingsCenter />
      </ThemeProvider>,
      { initialEntries: ["/settings/general"] },
    );

    expect(container.querySelector('[data-theme="dark"]')).not.toBeNull();
  });

  it("persists wide mode from General settings", async () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    const wideMode = screen.getByRole("switch", { name: "Wide mode" });
    expect(wideMode).not.toBeChecked();

    await userEvent.click(wideMode);

    expect(wideMode).toBeChecked();
    expect(localStorage.getItem("qwenpaw_chat_wide_mode")).toBe("true");
  });

  it("returns to the page that opened settings", async () => {
    renderWithProviders(
      <>
        <SettingsCenter />
        <LocationProbe />
      </>,
      {
        initialEntries: [
          {
            pathname: "/settings/general",
            state: { settingsReturnTo: "/files" },
          },
        ],
      },
    );

    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/files");
  });

  it("keeps agent-scoped automation out of global settings", () => {
    const EmptyPage = () => null;
    registry.routes = [
      { id: "core.security", path: "/security", Component: EmptyPage },
      { id: "core.channels", path: "/channels", Component: EmptyPage },
      { id: "core.cron-jobs", path: "/cron-jobs", Component: EmptyPage },
      { id: "core.heartbeat", path: "/heartbeat", Component: EmptyPage },
    ];

    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    const dataGroup = screen
      .getByRole("heading", { name: "Data & security" })
      .closest("section");
    expect(dataGroup).not.toBeNull();
    expect(within(dataGroup!).getByText("Security")).toBeVisible();
    expect(screen.queryByText("Channels")).toBeNull();
    expect(screen.queryByText("Cron Jobs")).toBeNull();
    expect(screen.queryByText("Heartbeat")).toBeNull();
  });

  it("opens with language, theme and sidebar preferences", () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    expect(screen.getByRole("heading", { name: "Settings" })).toBeVisible();
    expect(screen.getByText("Language")).toBeVisible();
    expect(screen.getByText("Theme")).toBeVisible();
    expect(screen.getByText("Sidebar content")).toBeVisible();
    expect(screen.getByRole("button", { name: "Customize" })).toBeVisible();
  });

  it("opens plugin settings at the original registered path", async () => {
    const PluginSettings = () => <div>Plugin configuration form</div>;
    registry.routes = [
      {
        id: "example.settings",
        path: "/example-settings",
        Component: PluginSettings,
      },
    ];
    registry.settingsMenu = [
      {
        id: "example.settings.menu",
        location: "primary.settings",
        label: "Example extension",
        route: "example.settings",
      },
    ];

    renderWithProviders(
      <>
        <SettingsCenter />
        <LocationProbe />
      </>,
      { initialEntries: ["/settings/general"] },
    );

    await userEvent.click(
      screen.getByRole("button", { name: /Example extension/i }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/example-settings",
    );
    expect(
      screen.queryByText("Plugin configuration form"),
    ).not.toBeInTheDocument();
  });

  it("preserves href-only plugin settings", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    registry.settingsMenu = [
      {
        id: "example.external-settings",
        location: "primary.settings",
        label: "External settings",
        href: "https://example.com/settings",
      },
    ];

    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });
    await userEvent.click(
      screen.getByRole("button", { name: /External settings/i }),
    );

    expect(open).toHaveBeenCalledWith(
      "https://example.com/settings",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("allows a plugin shortcut to be selected for the sidebar", async () => {
    registry.routes = [
      {
        id: "example.settings",
        path: "/example-settings",
        Component: () => null,
      },
    ];
    registry.settingsMenu = [
      {
        id: "example.settings.menu",
        location: "primary.settings",
        label: "Example extension",
        route: "example.settings",
      },
    ];

    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/navigation"],
    });

    const checkbox = screen.getByRole("checkbox", {
      name: "Example extension",
    });
    expect(checkbox).toBeChecked();

    await userEvent.click(checkbox);

    expect(checkbox).not.toBeChecked();
    expect(useSidebarModeStore.getState().hiddenPluginItemIds).toContain(
      "example.settings.menu",
    );
    expect(screen.getAllByText("Example extension").length).toBeGreaterThan(0);
  });

  it("allows a global settings page to be added to the sidebar", async () => {
    registry.routes = [
      {
        id: "core.security",
        path: "/security",
        Component: () => null,
      },
    ];
    registry.settingsMenu = [
      {
        id: "core.security",
        location: "primary.settings",
        label: "Security",
        route: "core.security",
      },
    ];

    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/navigation"],
    });

    expect(
      screen.getByRole("heading", { name: "Global settings" }),
    ).toBeVisible();
    const checkbox = screen.getByRole("checkbox", { name: "Security" });
    expect(checkbox).not.toBeChecked();

    await userEvent.click(checkbox);

    expect(checkbox).toBeChecked();
    expect(useSidebarModeStore.getState().focusItemIds).toContain(
      "core.security",
    );
  });

  it("controls built-in and plugin shortcuts independently by section", async () => {
    registry.routes = [
      { id: "core.security", path: "/security", Component: () => null },
      {
        id: "example.settings",
        path: "/example-settings",
        Component: () => null,
      },
    ];
    registry.settingsMenu = [
      {
        id: "core.security",
        location: "primary.settings",
        label: "Security",
        route: "core.security",
      },
      {
        id: "example.settings.menu",
        location: "primary.settings",
        label: "Example extension",
        route: "example.settings",
      },
    ];

    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/navigation"],
    });

    const security = screen.getByRole("checkbox", { name: "Security" });
    const plugin = screen.getByRole("checkbox", {
      name: "Example extension",
    });
    expect(security).not.toBeChecked();
    expect(plugin).toBeChecked();

    const globalSection = screen
      .getByRole("heading", { name: "Global settings" })
      .closest("section");
    const pluginSection = screen
      .getByRole("heading", { name: "Plugin shortcuts" })
      .closest("section");
    expect(globalSection).not.toBeNull();
    expect(pluginSection).not.toBeNull();

    await userEvent.click(
      within(globalSection!).getByRole("button", { name: "Select all" }),
    );
    expect(security).toBeChecked();
    expect(plugin).toBeChecked();

    await userEvent.click(
      within(pluginSection!).getByRole("button", { name: "Invert" }),
    );
    expect(security).toBeChecked();
    expect(plugin).not.toBeChecked();
  });
});
