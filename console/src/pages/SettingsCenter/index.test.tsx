import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Grid } from "antd";
import type { ComponentType } from "react";
import { useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { themeApi } from "@/api/modules/theme";
import { ThemeProvider, useTheme } from "@/contexts/ThemeContext";
import type { MenuItem } from "@/plugins/registry/types";
import { DEFAULT_FOCUS_ITEM_IDS, useSidebarStore } from "@/stores/sidebarStore";
import { useAgentStore } from "@/stores/agentStore";

// JSDOM cannot run NumberFlow's custom-element animation lifecycle.
vi.mock("@number-flow/react", () => ({
  default: ({ value, suffix }: { value: number; suffix?: string }) => (
    <span>
      {value}
      {suffix}
    </span>
  ),
}));

// Verify editor state separately from Motion's browser-only exit lifecycle.
vi.mock("@/components/interaction/SharedModal", () => ({
  SharedModal: ({ open, onCancel, children }: import("antd").ModalProps) =>
    open ? (
      <div role="dialog">
        <button onClick={onCancel}>Close</button>
        {children}
      </div>
    ) : null,
}));

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
    vi.spyOn(Grid, "useBreakpoint").mockReturnValue({ md: true });
    registry.routes = [];
    registry.agentMenu = [];
    registry.settingsMenu = [];
    registry.pluginLoading = false;
    useAgentStore.setState({
      selectedAgent: "native",
      agents: ["qwenpaw", "codex", "qoder"].map((backend) => ({
        id: backend === "qwenpaw" ? "native" : backend,
        name: `${backend} target`,
        description: "",
        workspace_dir: "",
        enabled: true,
        backend,
      })),
    });
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

  it("uses dark preset swatches when dark theme is active", async () => {
    localStorage.setItem("qwenpaw-theme", "dark");

    const { container } = renderWithProviders(
      <ThemeProvider>
        <SettingsCenter />
      </ThemeProvider>,
      { initialEntries: ["/settings/general"] },
    );

    expect(container.querySelector('[data-theme="dark"]')).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Custom theme" }));
    await userEvent.click(
      screen.getByRole("combobox", { name: "Theme palette" }),
    );

    const swatches = Array.from(
      document.querySelectorAll<HTMLElement>('[aria-hidden="true"]'),
    ).filter((element) => element.textContent === "Aa");
    expect(swatches.length).toBeGreaterThanOrEqual(6);
    expect(
      swatches.every(
        (swatch) => swatch.style.background !== "rgb(255, 255, 255)",
      ),
    ).toBe(true);
  });

  it("flushes an edited theme when the editor closes", async () => {
    vi.spyOn(themeApi, "get").mockResolvedValue({ radius: "8px" });
    const update = vi
      .spyOn(themeApi, "update")
      .mockImplementation(async (theme) => theme);
    function ThemeProbe() {
      const { previewTheme } = useTheme();
      return <output data-testid="theme-preview">{previewTheme.radius}</output>;
    }
    renderWithProviders(
      <ThemeProvider>
        <SettingsCenter />
        <ThemeProbe />
      </ThemeProvider>,
      { initialEntries: ["/settings/general"] },
    );
    await waitFor(() =>
      expect(screen.getByTestId("theme-preview")).toHaveTextContent("8px"),
    );
    await userEvent.click(screen.getByRole("button", { name: "Custom theme" }));
    fireEvent.keyDown(screen.getByRole("slider"), {
      key: "ArrowRight",
      keyCode: 39,
    });
    expect(screen.getByTestId("theme-preview")).toHaveTextContent("9px");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(update).toHaveBeenCalledWith({ radius: "9px" }));
    expect(screen.getByTestId("theme-preview")).toHaveTextContent("9px");
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
    await waitFor(() =>
      expect(within(messageDisplay!).getByText("Message width")).toBeVisible(),
    );
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

  it("offers color palettes without font controls", async () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    await userEvent.click(screen.getByRole("button", { name: "Custom theme" }));
    const palette = screen.getByRole("combobox", {
      name: "Theme palette",
    });
    await userEvent.click(palette);

    const swatches = Array.from(
      document.querySelectorAll<HTMLElement>('[aria-hidden="true"]'),
    ).filter((element) => element.textContent === "Aa");
    expect(swatches.length).toBeGreaterThanOrEqual(6);
    expect(
      swatches.every(
        (swatch) => swatch.style.background === "rgb(255, 255, 255)",
      ),
    ).toBe(true);

    for (const name of [
      "QwenPaw",
      "Codex",
      "Ayu",
      "Catppuccin",
      "Dracula",
      "Everforest",
    ]) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
    expect(screen.queryByText("Font family")).not.toBeInTheDocument();
    expect(screen.queryByText("Monospace family")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText("Dracula"));

    expect(
      screen
        .getAllByText("Dracula")
        .some((element) => element.closest(".ant-select-selection-item")),
    ).toBe(true);
  });

  it("persists message display preferences", async () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    await waitFor(() => expect(screen.getByText("Card view")).toBeVisible());
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

  it("includes scheduled tasks in agent settings", () => {
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
    expect(within(agentGroup!).getByText("Cron Jobs")).toBeVisible();
    expect(within(agentGroup!).getByText("Heartbeat")).toBeVisible();
  });

  it("keeps sidebar customization out of General settings", async () => {
    renderWithProviders(<SettingsCenter />, {
      initialEntries: ["/settings/general"],
    });

    expect(
      screen.queryByRole("heading", { name: "Settings" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to app" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "General" })).toBeVisible();
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Appearance & language" }),
      ).toBeVisible(),
    );
    expect(screen.getByText("Language")).toBeVisible();
    await waitFor(() => expect(screen.getByText("Theme")).toBeVisible());
    expect(screen.getByText("Message width")).toBeVisible();
    expect(screen.queryByText("Sidebar content")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sidebar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Sidebar", level: 3 }),
    ).toBeVisible();
    expect(
      screen.queryByText("Language, theme and application behavior"),
    ).not.toBeInTheDocument();
  });

  it("expands agent pages and keeps their sidebar controls", async () => {
    const EmptyPage = () => null;
    const ImportPage = () => <div>PawPort import workflow</div>;
    const agentPages = [
      ["core.channels", "/channels", "Channels"],
      ["core.heartbeat", "/heartbeat", "Heartbeat"],
      ["core.skills", "/skills", "Skills"],
      ["core.tools", "/tools", "Tools"],
      ["core.mcp", "/mcp", "MCP"],
      ["core.acp", "/acp", "ACP"],
      ["core.import", "/imports", "Import"],
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
        Component: id === "core.import" ? ImportPage : EmptyPage,
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
      within(agentGroup!)
        .getAllByRole("button", { name: /^(ACP|Import|Configuration)$/ })
        .map((button) => button.textContent),
    ).toEqual(["ACP", "Import", "Configuration"]);
    expect(useSidebarStore.getState().focusItemIds).not.toContain(
      "core.import",
    );
    expect(screen.getByRole("button", { name: "Extension" })).toBeVisible();
    for (const label of [
      "Sessions",
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

    await userEvent.click(
      within(agentGroup!).getByRole("button", { name: "Import" }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings/import",
    );
    expect(screen.getByText("PawPort import workflow")).toBeVisible();

    const search = screen.getByPlaceholderText("Search settings");
    await userEvent.type(search, "other AI applications");
    expect(screen.getByRole("button", { name: "Import" })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "ACP" }),
    ).not.toBeInTheDocument();
    await userEvent.clear(search);

    await userEvent.click(screen.getByRole("button", { name: "General" }));
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { level: 3, name: "Agent configuration" }),
      ).toBeVisible(),
    );
    expect(
      screen.getByRole("button", { name: "Move Sessions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Move Cron Jobs" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Move Marketplace" }),
    ).toBeVisible();
  });

  it.each(["codex", "qoder"])(
    "hides Import for %s while preserving the route and restoring it for QwenPaw",
    async (backend) => {
      registry.routes = [
        { id: "core.acp", path: "/acp", Component: () => null },
        { id: "core.import", path: "/imports", Component: () => null },
      ];
      renderWithProviders(
        <>
          <SettingsCenter />
          <LocationProbe />
        </>,
        { initialEntries: ["/settings/import"] },
      );

      expect(screen.getByRole("button", { name: "Import" })).toBeVisible();
      act(() => useAgentStore.setState({ selectedAgent: backend }));
      expect(screen.queryByRole("button", { name: "Import" })).toBeNull();
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/settings/import",
      );

      await userEvent.type(
        screen.getByPlaceholderText("Search settings"),
        "other AI applications",
      );
      expect(screen.getByText("No matching settings")).toBeVisible();
      act(() => useAgentStore.setState({ selectedAgent: "native" }));
      expect(screen.getByRole("button", { name: "Import" })).toBeVisible();
    },
  );

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
      screen.getByRole("button", { name: "Example extension" }),
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
      screen.getByRole("button", { name: "External settings" }),
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
      initialEntries: ["/settings/general"],
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Remove Example extension" }),
    );
    expect(useSidebarStore.getState().hiddenPluginItemIds).not.toContain(
      "example.settings.menu",
    );
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
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
      initialEntries: ["/settings/general"],
    });

    expect(
      screen.queryByRole("heading", { level: 3, name: "Global settings" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { level: 3, name: "Global settings" }),
      ).toBeVisible(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Add Security" }));
    expect(useSidebarStore.getState().focusItemIds).not.toContain(
      "core.security",
    );
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(useSidebarStore.getState().focusItemIds).toContain("core.security");
  });

  it("finds nested settings and navigates to their page", async () => {
    registry.routes = [
      {
        id: "core.cron-jobs",
        path: "/cron-jobs",
        Component: () => <div>Jobs page</div>,
      },
    ];
    renderWithProviders(
      <>
        <SettingsCenter />
        <LocationProbe />
      </>,
      { initialEntries: ["/settings/cron-jobs"] },
    );
    await userEvent.type(
      screen.getByPlaceholderText("Search settings"),
      "sidebar",
    );
    const navigation = screen.getByRole("navigation");
    expect(
      within(navigation).getByRole("button", { name: "General" }),
    ).toBeInTheDocument();
    await userEvent.click(
      within(navigation).getByRole("button", { name: "Sidebar" }),
    );
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings/general",
    );
    expect(
      screen.getByRole("heading", { name: "Sidebar" }),
    ).toBeInTheDocument();
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
      initialEntries: ["/settings/general"],
    });

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Add Security" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Remove Example extension" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(useSidebarStore.getState().focusItemIds).toContain("core.security");
    expect(useSidebarStore.getState().hiddenPluginItemIds).toContain(
      "example.settings.menu",
    );
  });
});
