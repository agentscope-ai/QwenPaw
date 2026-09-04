import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentType } from "react";
import { useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { ThemeProvider } from "@/contexts/ThemeContext";
import type { MenuItem } from "@/plugins/registry/types";
import { DEFAULT_FOCUS_ITEM_IDS, useSidebarStore } from "@/stores/sidebarStore";

const registry = vi.hoisted(() => ({
  routes: [] as Array<{
    id: string;
    path: string;
    Component: ComponentType;
  }>,
  agentMenu: [] as MenuItem[],
  settingsMenu: [] as MenuItem[],
  pluginLoading: false,
}));

vi.mock("@/plugins/registry/hooks", () => ({
  useRoutes: () => registry.routes,
  useMenuItems: (location: string) => {
    if (location === "primary.agentScoped") return registry.agentMenu;
    if (location === "primary.settings") return registry.settingsMenu;
    return [];
  },
}));

vi.mock("@/plugins/PluginContext", () => ({
  usePlugins: () => ({ loading: registry.pluginLoading }),
}));

import SettingsCenter from ".";

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

describe("SettingsCenter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    registry.routes = [];
    registry.agentMenu = [];
    registry.settingsMenu = [];
    registry.pluginLoading = false;
    localStorage.removeItem("qwenpaw_chat_wide_mode");
    localStorage.removeItem("qwenpaw_tool_calls_default_expanded");
    localStorage.removeItem("qwenpaw_tool_display_mode");
    localStorage.removeItem("qwenpaw_assistant_message_display_mode");
    localStorage.removeItem("qwenpaw_show_thinking");
    localStorage.removeItem("qwenpaw-theme");
    useSidebarStore.setState({
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

  it("persists the standard and wide message widths", async () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    const appearance = screen
      .getByRole("heading", { name: "Appearance & language" })
      .closest("section");
    const messageDisplay = screen
      .getByRole("heading", { name: "Message display" })
      .closest("section");
    expect(appearance).not.toBeNull();
    expect(messageDisplay).not.toBeNull();
    expect(within(messageDisplay!).getByText("Message width")).toBeVisible();
    expect(within(appearance!).getByText("Desktop Mode")).toBeVisible();
    expect(
      within(appearance!).getByRole("button", { name: "Open" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Desktop app" }),
    ).not.toBeInTheDocument();
    const thinkingDisplay = within(messageDisplay!).getByText("Show thinking");
    const toolDisplay = within(messageDisplay!).getByText("Tool display");
    expect(
      thinkingDisplay.compareDocumentPosition(toolDisplay) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const standard = within(messageDisplay!).getByText("Standard");
    const wide = within(messageDisplay!).getByText("Wide");

    await userEvent.click(wide);

    expect(localStorage.getItem("qwenpaw_chat_wide_mode")).toBe("true");

    await userEvent.click(standard);

    expect(localStorage.getItem("qwenpaw_chat_wide_mode")).toBeNull();
  });

  it("persists message display preferences", async () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    expect(screen.getByText("Card view")).toBeVisible();
    const thinkingSwitch = screen.getByRole("switch");
    expect(thinkingSwitch).toBeChecked();
    await userEvent.click(thinkingSwitch);
    await userEvent.click(screen.getByText("Raw parameters"));

    await userEvent.click(screen.getByText("Collapse process"));

    expect(localStorage.getItem("qwenpaw_tool_display_mode")).toBe(
      "raw-input-output",
    );
    expect(localStorage.getItem("qwenpaw_show_thinking")).toBe("false");
    const storedMode = localStorage.getItem(
      "qwenpaw_assistant_message_display_mode",
    );
    expect(storedMode).toBe("process-collapsed");
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

    await userEvent.click(screen.getByRole("button", { name: "Back to app" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/files");
  });

  it("redirects an unknown settings page while preserving the return path", async () => {
    renderWithProviders(
      <>
        <SettingsCenter />
        <LocationProbe />
      </>,
      {
        initialEntries: [
          {
            pathname: "/settings/unknown-page",
            state: { settingsReturnTo: "/files" },
          },
        ],
      },
    );

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/settings/general",
      );
    });
    expect(screen.getByRole("heading", { name: "General" })).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Back to app" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/files");
  });

  it("does not redirect a potential plugin deep link while plugins load", async () => {
    registry.pluginLoading = true;
    const view = renderWithProviders(
      <>
        <SettingsCenter />
        <LocationProbe />
      </>,
      { initialEntries: ["/settings/plugin-account"] },
    );

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings/plugin-account",
    );
    expect(screen.queryByRole("heading", { name: "General" })).toBeNull();

    registry.pluginLoading = false;
    view.rerender(
      <>
        <SettingsCenter />
        <LocationProbe />
      </>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/settings/general",
      );
    });
  });

  it("keeps operational workspaces out of settings navigation", () => {
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

    const globalGroup = screen
      .getByRole("heading", { name: "Global settings" })
      .closest("section");
    const agentGroup = screen
      .getByRole("heading", { name: "Agent configuration" })
      .closest("section");
    expect(globalGroup).not.toBeNull();
    expect(agentGroup).not.toBeNull();
    expect(within(globalGroup!).getByText("Security")).toBeVisible();
    expect(within(globalGroup!).queryByText("Channels")).toBeNull();
    expect(within(globalGroup!).queryByText("Cron Jobs")).toBeNull();
    expect(within(globalGroup!).queryByText("Heartbeat")).toBeNull();
    expect(within(agentGroup!).getByText("Channels")).toBeVisible();
    expect(within(agentGroup!).queryByText("Cron Jobs")).toBeNull();
    expect(within(agentGroup!).getByText("Heartbeat")).toBeVisible();
  });

  it("keeps sidebar customization out of General settings", () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    expect(
      screen.queryByRole("heading", { name: "Settings" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to app" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "General" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Appearance & language" }),
    ).toBeVisible();
    expect(screen.getByText("Language")).toBeVisible();
    expect(screen.getByText("Theme")).toBeVisible();
    expect(screen.getByText("Message width")).toBeVisible();
    expect(screen.queryByText("Sidebar content")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sidebar" })).toBeVisible();
    expect(
      screen.queryByText("Language, theme and application behavior"),
    ).not.toBeInTheDocument();
  });

  it("expands agent pages and keeps their sidebar controls", async () => {
    const EmptyPage = () => null;
    const agentPages = [
      ["core.channels", "/channels", "Channels"],
      ["core.heartbeat", "/heartbeat", "Heartbeat"],
      ["core.skills", "/skills", "Skills"],
      ["core.tools", "/tools", "Tools"],
      ["core.mcp", "/mcp", "MCP"],
      ["core.acp", "/acp", "ACP"],
      ["core.agent-config", "/agent-config", "Configuration"],
    ] as const;
    const operationalPages = [
      ["core.sessions", "/sessions"],
      ["core.cron-jobs", "/cron-jobs"],
      ["core.files", "/files"],
      ["core.agent-stats", "/agent-stats"],
      ["core.checkpoints", "/checkpoints"],
    ] as const;
    registry.routes = [
      { id: "core.marketplace", path: "/market", Component: EmptyPage },
      ...agentPages.map(([id, path]) => ({
        id,
        path,
        Component: EmptyPage,
      })),
      ...operationalPages.map(([id, path]) => ({
        id,
        path,
        Component: EmptyPage,
      })),
    ];
    registry.agentMenu = [
      {
        id: "core.marketplace",
        location: "primary.agentScoped",
        label: "Marketplace",
        route: "core.marketplace",
      },
      {
        id: "core.sessions",
        location: "primary.agentScoped",
        label: "Sessions",
        route: "core.sessions",
      },
      {
        id: "core.cron-jobs",
        location: "primary.agentScoped",
        label: "Cron Jobs",
        route: "core.cron-jobs",
      },
    ];

    renderWithProviders(
      <>
        <SettingsCenter />
        <LocationProbe />
      </>,
      { initialEntries: ["/settings/general"] },
    );

    const agentGroup = screen
      .getByRole("heading", { name: "Agent configuration" })
      .closest("section");
    expect(agentGroup).not.toBeNull();
    for (const [, , label] of agentPages) {
      expect(
        within(agentGroup!).getByRole("button", { name: label }),
      ).toBeVisible();
    }
    expect(
      screen.queryByRole("button", { name: "Marketplace" }),
    ).not.toBeInTheDocument();
    for (const label of [
      "Sessions",
      "Cron Jobs",
      "Files",
      "Agent Statistics",
      "Checkpoints",
    ]) {
      expect(
        within(agentGroup!).queryByRole("button", { name: label }),
      ).not.toBeInTheDocument();
    }

    await userEvent.click(
      within(agentGroup!).getByRole("button", { name: "Tools" }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent("/settings/tools");

    await userEvent.click(screen.getByRole("button", { name: "Sidebar" }));

    expect(
      screen.getByRole("heading", {
        level: 3,
        name: "Agent configuration",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("checkbox", { name: "Sessions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Cron Jobs" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Extension" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Extension" })).toBeDisabled();
  });

  it("moves resource management pages into Global settings", () => {
    const EmptyPage = () => null;
    registry.routes = [
      { id: "core.agents", path: "/agents", Component: EmptyPage },
      { id: "core.models", path: "/models", Component: EmptyPage },
      { id: "core.skill-pool", path: "/skill-pool", Component: EmptyPage },
    ];

    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    expect(
      screen.queryByRole("heading", { name: "Resource management" }),
    ).not.toBeInTheDocument();
    const globalGroup = screen
      .getByRole("heading", { name: "Global settings" })
      .closest("section");
    expect(globalGroup).not.toBeNull();
    expect(within(globalGroup!).getByText("Agent Management")).toBeVisible();
    expect(within(globalGroup!).getByText("Models")).toBeVisible();
    expect(within(globalGroup!).getByText("Skill Pool")).toBeVisible();
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
    expect(useSidebarStore.getState().hiddenPluginItemIds).toContain(
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
      screen.getByRole("heading", { level: 3, name: "Global settings" }),
    ).toBeVisible();
    const checkbox = screen.getByRole("checkbox", { name: "Security" });
    expect(checkbox).not.toBeChecked();

    await userEvent.click(checkbox);

    expect(checkbox).toBeChecked();
    expect(useSidebarStore.getState().focusItemIds).toContain("core.security");
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
      .getByRole("heading", { level: 3, name: "Global settings" })
      .closest("section");
    const pluginSection = screen
      .getByRole("heading", { name: "Plugin features" })
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
