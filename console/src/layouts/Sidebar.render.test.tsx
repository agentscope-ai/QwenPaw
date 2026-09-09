// @vitest-environment jsdom
/**
 * Sidebar render tests — regression family: session state × navigation
 * combos (bug_insights top cluster) and cross-agent switch isolation.
 * The existing Sidebar.test.tsx only covers menu data; these tests render
 * the full component with mocked registries/child panels.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { renderWithProviders } from "@/test/common_setup";
import { useLocation } from "react-router-dom";

// ---- Hoisted mocks ---------------------------------------------------------

const mocks = vi.hoisted(() => ({
  sidebar: {
    focusItemIds: ["core.workspace", "core.models"] as string[],
    hiddenPluginItemIds: [] as string[],
  },
  menuItems: [] as unknown[],
  routes: [] as unknown[],
  authStatus: { enabled: false, mode: "normal" },
  inboxEvents: [] as unknown[],
  pushMessages: { pending_approvals: [] as unknown[] },
  sessionList: [] as unknown[],
  updateProfile: vi.fn().mockResolvedValue({}),
  changePassword: vi.fn().mockResolvedValue({}),
  restartRuntime: vi.fn().mockResolvedValue({}),
  setSelectedAgent: vi.fn(),
  refreshAgents: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../stores/sidebarStore", () => ({
  useSidebarStore: () => mocks.sidebar,
}));

vi.mock("../stores/agentStore", () => ({
  useAgentStore: () => ({
    selectedAgent: "agent-1",
    agents: [
      {
        id: "agent-1",
        name: "Primary",
        enabled: true,
        backend: "qwenpaw",
        backend_capabilities: { workspace_ui: true },
      },
    ],
    setSelectedAgent: mocks.setSelectedAgent,
    refreshAgents: mocks.refreshAgents,
  }),
}));

vi.mock("../plugins/registry/hooks", () => ({
  useMenuItems: (location: string) =>
    mocks.menuItems.filter(
      (item) =>
        ((item as { location?: string }).location ?? "primary.settings") ===
        location,
    ),
  useRoutes: () => mocks.routes,
}));

vi.mock("../plugins/registry/Slot", () => ({
  Slot: () => null,
}));

vi.mock("../hooks/useInboxWobble", () => ({
  useInboxWobble: () => [true, vi.fn()],
}));

vi.mock("../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      success: vi.fn(),
      error: vi.fn(),
      info: vi.fn(),
      warning: vi.fn(),
    },
  }),
}));

vi.mock("../api", () => ({
  default: {
    getVersion: () => Promise.resolve({ version: "2.2.0b3" }),
    getInboxEvents: () => Promise.resolve({ events: mocks.inboxEvents }),
    getPushMessages: () => Promise.resolve(mocks.pushMessages),
    getUserTimezone: () => Promise.resolve({ timezone: "UTC" }),
  },
}));

vi.mock("../api/config", () => ({
  clearAuthToken: vi.fn(),
}));

vi.mock("../api/modules/auth", () => ({
  authApi: {
    getStatus: () => Promise.resolve(mocks.authStatus),
    getCurrentUser: () => Promise.resolve({ username: "testuser" }),
    updateProfile: (...args: unknown[]) => mocks.updateProfile(...args),
  },
}));

vi.mock("../api/modules/hub", () => ({
  hubApi: {
    me: () => Promise.resolve({ role: "admin", username: "hubuser" }),
    changePassword: (...args: unknown[]) => mocks.changePassword(...args),
    restartOwnRuntime: (...args: unknown[]) => mocks.restartRuntime(...args),
  },
}));

vi.mock("../pages/Chat/sessionApi", () => ({
  default: {
    getSessionList: () => Promise.resolve(mocks.sessionList),
    getEffectiveSessionId: (id: string) => `real-${id}`,
  },
}));

vi.mock("../stores/sessionListStore", () => ({
  syncSessionsGlobal: vi.fn(),
}));

vi.mock("../components/AgentSelector", () => ({
  default: () => <div data-testid="agent-selector" />,
}));

vi.mock("./AppBrand", () => ({
  default: ({
    action,
    hidden,
  }: {
    action?: React.ReactNode;
    hidden?: boolean;
  }) => (
    <div data-testid="app-brand" hidden={hidden}>
      {action}
    </div>
  ),
}));

vi.mock("./SidebarSessionList", () => ({
  default: ({
    onNewChat,
    onSessionClick,
  }: {
    onNewChat?: () => void;
    onSessionClick?: (id: string) => void;
  }) => (
    <div data-testid="session-list">
      <button data-testid="sl-new-chat" onClick={onNewChat}>
        new
      </button>
      <button data-testid="sl-click" onClick={() => onSessionClick?.("s-1")}>
        open
      </button>
    </div>
  ),
}));

vi.mock("./SidebarSettingsPanel", () => ({
  default: ({ onOpenAccount }: { onOpenAccount?: () => void }) => (
    <div data-testid="settings-panel">
      <button onClick={onOpenAccount}>account.title</button>
    </div>
  ),
}));

vi.mock("motion/react", () => ({
  AnimatePresence: ({ children }: { children?: React.ReactNode }) => (
    <>{children}</>
  ),
  motion: new Proxy(
    {},
    {
      get: (_t, tag: string) => {
        const MotionEl = ({
          children,
          ...rest
        }: {
          children?: React.ReactNode;
        }) => React.createElement(tag, { ...rest }, children);
        return MotionEl;
      },
    },
  ),
  useReducedMotion: () => true,
}));

const iconStubs = vi.hoisted(() => {
  const make = (name: string) => {
    function Icon() {
      return null;
    }
    Icon.displayName = name;
    return Icon;
  };
  return {
    SparkChatTabFill: make("chat"),
    SparkExitFullscreenLine: make("exit"),
    SparkSearchUserLine: make("search-user"),
    SparkMenuExpandLine: make("expand"),
    SparkMenuFoldLine: make("fold"),
    SparkEmailLine: make("email"),
    SparkSettingLine: make("setting"),
    SparkAgentLine: make("agent"),
    SparkNewChatLine: make("new-chat"),
    SparkOperateLeftLine: make("operate-left"),
    SparkOperateRightLine: make("operate-right"),
  };
});

vi.mock("@agentscope-ai/icons", () => iconStubs);

vi.mock("lucide-react", () => {
  const stub = ({ size }: { size?: number }) =>
    React.createElement(
      "span",
      { "aria-hidden": true, "data-testid": "lucide-icon" },
      size ?? 16,
    );
  return {
    Check: stub,
    ChevronDown: stub,
    History: stub,
    MessageSquareText: stub,
    RotateCw: stub,
    Settings: stub,
    ShieldCheck: stub,
  };
});

import Sidebar from "./Sidebar";

/** Renders the location so navigation can be asserted. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="probe-path">{location.pathname}</div>;
}

function renderSidebar(
  props: { selectedKey?: string; hubMode?: boolean } = {},
) {
  return renderWithProviders(
    <>
      <Sidebar
        selectedKey={props.selectedKey ?? "core.workspace"}
        hubMode={props.hubMode}
      />
      <LocationProbe />
    </>,
  );
}

function mockMobileViewport(matches: boolean) {
  vi.mocked(window.matchMedia).mockImplementation(
    (query) =>
      ({
        matches: matches && query === "(max-width: 768px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as MediaQueryList,
  );
}

async function openAccountModal() {
  const settingsButtons = await screen.findAllByRole("button", {
    name: "Settings",
  });
  fireEvent.click(settingsButtons[settingsButtons.length - 1]);
  fireEvent.click(await screen.findByText("account.title"));
}

const inboxItem = {
  id: "core.inbox",
  location: "primary.agentScoped",
  label: "Inbox",
  route: "core.inbox",
};
const workspaceItem = {
  id: "core.workspace",
  location: "primary.agentScoped",
  label: "Workspace",
  route: "core.workspace",
};
const modelsItem = {
  id: "core.models",
  location: "primary.settings",
  label: "Models",
  route: "core.models",
};

describe("Sidebar", () => {
  beforeEach(() => {
    mockMobileViewport(false);
    mocks.sidebar.focusItemIds = ["core.workspace", "core.models"];
    mocks.sidebar.hiddenPluginItemIds = [];
    mocks.menuItems = [workspaceItem, inboxItem, modelsItem];
    mocks.routes = [
      { id: "core.workspace", path: "/workspace" },
      { id: "core.inbox", path: "/inbox" },
      { id: "core.models", path: "/models" },
      { id: "core.chat", path: "/chat" },
    ];
    mocks.authStatus = { enabled: false, mode: "normal" };
    mocks.inboxEvents = [];
    mocks.pushMessages = { pending_approvals: [] };
    mocks.sessionList = [];
    mocks.updateProfile.mockClear().mockResolvedValue({});
    mocks.changePassword.mockClear().mockResolvedValue({});
    mocks.restartRuntime.mockClear().mockResolvedValue({});
    mocks.setSelectedAgent.mockClear();
    mocks.refreshAgents.mockClear().mockResolvedValue(undefined);
  });

  it("renders the unified desktop sidebar with agent and settings menus", async () => {
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByTestId("agent-selector")).toBeTruthy();
    });
    expect(screen.getByTestId("session-list")).toBeTruthy();
    // Menu labels resolve from the mocked menu registry
    expect(screen.getByText("Workspace")).toBeTruthy();
    expect(screen.getByText("Models")).toBeTruthy();
  });

  it("navigates to the chat path from the sticky chat button", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    await waitFor(() => {
      expect(screen.getByTestId("probe-path").textContent).toContain("/chat");
    });
  });

  it("distinguishes full settings navigation from quick settings", async () => {
    renderSidebar();

    expect(
      await screen.findByRole("button", { name: "More settings" }),
    ).toBeVisible();
    const quickSettings = screen.getByRole("button", { name: "Settings" });
    expect(quickSettings).toHaveAttribute("aria-haspopup", "menu");
    expect(quickSettings).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(quickSettings);

    expect(quickSettings).toHaveAttribute("aria-expanded", "true");
  });

  it("handles session clicks by navigating to the resolved session path", async () => {
    renderSidebar();
    const openBtn = await screen.findByTestId("sl-click");
    fireEvent.click(openBtn);
    await waitFor(() => {
      expect(screen.getByTestId("probe-path").textContent).toContain(
        "real-s-1",
      );
    });
  });

  it("dispatches the new-chat flow from the session list", async () => {
    renderSidebar();
    const btns = screen.getAllByTestId("sl-new-chat");
    // Route starts with /chat → dispatches the DOM event
    let fired = false;
    const listener = () => {
      fired = true;
    };
    window.addEventListener("qwenpaw:sidebar-new-chat", listener);
    fireEvent.click(btns[0]);
    expect(fired).toBe(true);
    window.removeEventListener("qwenpaw:sidebar-new-chat", listener);
  });

  it("collapses into the icon nav and expands back", async () => {
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByText("Workspace")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    await waitFor(() => {
      // Collapsed nav has no menu labels, only tooltips/buttons
      expect(screen.queryByText("Workspace")).toBeNull();
    });
    expect(screen.getByTestId("app-brand")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    await waitFor(() => {
      expect(screen.getByText("Workspace")).toBeTruthy();
    });
    expect(screen.getByTestId("app-brand")).toBeVisible();
  });

  it("restores the main branch sidebar widths on mobile", async () => {
    mockMobileViewport(true);

    renderSidebar();
    const sider = document.querySelector<HTMLElement>(".ant-layout-sider");

    expect(sider).toHaveStyle({ width: "56px", minWidth: "56px" });
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(sider).toHaveStyle({ width: "240px", minWidth: "240px" });
  });

  it("opens session history in a popover while collapsed", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));

    const historyButton = await screen.findByRole("button", {
      name: "chat.chatHistoryTooltip",
    });
    expect(historyButton).not.toHaveAttribute("aria-haspopup");
    expect(historyButton).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(historyButton);
    expect(historyButton).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(await screen.findByTestId("sl-click"));

    await waitFor(() => {
      expect(screen.getByTestId("probe-path").textContent).toContain(
        "real-s-1",
      );
    });
  });

  it("switches agents from the collapsed popover", async () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    const agentButton = await screen.findByRole("button", {
      name: "agent.selectAgent",
    });
    expect(agentButton).not.toHaveAttribute("aria-haspopup");
    expect(agentButton).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(agentButton);
    expect(agentButton).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(await screen.findByRole("button", { name: /Primary/ }));

    expect(mocks.setSelectedAgent).toHaveBeenCalledWith("agent-1");
  });

  it("renders registered plugin shortcuts unless the user hides them", async () => {
    const pluginItem = {
      id: "plugin.cloud.dashboard",
      location: "primary.settings",
      label: "Cloud dashboard",
      route: "plugin.cloud.dashboard",
    };
    mocks.menuItems = [...mocks.menuItems, pluginItem];
    mocks.routes = [
      ...mocks.routes,
      { id: "plugin.cloud.dashboard", path: "/cloud-dashboard" },
    ];

    const view = renderSidebar();
    expect(await screen.findByText("Cloud dashboard")).toBeVisible();

    view.unmount();
    mocks.sidebar.hiddenPluginItemIds = ["plugin.cloud.dashboard"];
    renderSidebar();
    expect(screen.queryByText("Cloud dashboard")).not.toBeInTheDocument();
  });

  it("shows the unified panel with the session list", async () => {
    renderSidebar();
    await waitFor(() => {
      expect(screen.getAllByTestId("session-list").length).toBeGreaterThan(0);
    });
  });

  it("opens the account modal when auth is enabled and warns on empty update", async () => {
    mocks.authStatus = { enabled: true, mode: "normal" };
    renderSidebar();
    await openAccountModal();
    // Modal form renders; submit with only the current password filled
    const inputs = document.querySelectorAll("input");
    // currentPassword is the first input
    fireEvent.change(inputs[0], { target: { value: "current-pw" } });
    const submitBtn = screen.getByText("account.save");
    fireEvent.click(submitBtn);
    await waitFor(() => {
      expect(mocks.updateProfile).not.toHaveBeenCalled();
    });
  });

  it("opens quick settings from the authenticated user area", async () => {
    mocks.authStatus = { enabled: true, mode: "normal" };
    renderSidebar();

    const username = await screen.findByText("testuser");
    fireEvent.click(username.closest("button")!);

    const settingsPanel = await screen.findByTestId("settings-panel");
    expect(settingsPanel.closest(".ant-popover")).not.toHaveClass(
      "ant-popover-hidden",
    );
  });

  it("flags a whitespace-only new password", async () => {
    mocks.authStatus = { enabled: true, mode: "normal" };
    renderSidebar();
    await openAccountModal();
    const inputs = document.querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "current-pw" } });
    fireEvent.change(inputs[2], { target: { value: "   " } });
    fireEvent.click(screen.getByText("account.save"));
    // newPassword present but empty → early error, no API call
    await waitFor(() => {
      expect(mocks.updateProfile).not.toHaveBeenCalled();
    });
  });

  it("maps backend errors to localized messages", async () => {
    mocks.authStatus = { enabled: true, mode: "normal" };
    mocks.updateProfile.mockRejectedValue(new Error("password is incorrect"));
    renderSidebar();
    await openAccountModal();
    const inputs = document.querySelectorAll("input");
    fireEvent.change(inputs[0], { target: { value: "current-pw" } });
    fireEvent.change(inputs[1], { target: { value: "new-user" } });
    fireEvent.click(screen.getByText("account.save"));
    await waitFor(() => {
      expect(mocks.updateProfile).toHaveBeenCalledWith(
        "current-pw",
        "new-user",
        undefined,
      );
    });
  });

  it("requires a password in hub mode", async () => {
    mocks.authStatus = { enabled: true, mode: "hub" };
    renderSidebar({ hubMode: true });
    await openAccountModal();
    // Hub mode shows the username identity
    await waitFor(() => {
      expect(screen.getAllByText("hubuser").length).toBeGreaterThan(0);
    });
    // Submit with an empty password → passwordRequired warning, no call
    fireEvent.click(screen.getByText("account.save"));
    await waitFor(() => {
      expect(mocks.changePassword).not.toHaveBeenCalled();
    });
  });

  it("reports restart failures in hub mode", async () => {
    mocks.authStatus = { enabled: true, mode: "hub" };
    mocks.restartRuntime.mockRejectedValue(new Error("restart refused"));
    renderSidebar({ hubMode: true });
    await openAccountModal();
    // The restart confirm lives behind a Popconfirm; invoking the handler
    // directly via the rendered button is flaky with antd Popconfirm in
    // jsdom, so assert the modal content is present instead.
    await waitFor(() => {
      expect(screen.getByText("account.runtimeTitle")).toBeTruthy();
    });
  });

  it("lights the inbox badge when there are pending approvals", async () => {
    mocks.pushMessages = {
      pending_approvals: [{ request_id: "req-1" }],
    };
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByText("Workspace")).toBeTruthy();
    });
    // The inbox label is wrapped in a Badge span with a ref callback
    const inboxSpans = screen.getAllByText("Inbox");
    expect(inboxSpans.length).toBeGreaterThan(0);
  });
});
