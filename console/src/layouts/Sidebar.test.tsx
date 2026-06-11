import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "antd";
import { ThemeProvider } from "@/contexts/ThemeContext";
import Sidebar from "./Sidebar";

// ── i18n ──────────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

// ── router ────────────────────────────────────────────────────────────────────
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

// ── @agentscope-ai/icons mock ────────────────────────────────────────────────
vi.mock("@agentscope-ai/icons", () => {
  const Icon = ({ size }: { size?: number }) => (
    <span data-testid="mock-icon" style={{ fontSize: size }} />
  );
  return {
    SparkChatTabFill: Icon,
    SparkExitFullscreenLine: Icon,
    SparkSearchUserLine: Icon,
    SparkMenuExpandLine: Icon,
    SparkMenuFoldLine: Icon,
    SparkEmailLine: Icon,
  };
});

// ── API / stores / hooks mocks ────────────────────────────────────────────────
vi.mock("@/api/modules/auth", () => ({
  authApi: {
    getStatus: vi.fn().mockResolvedValue({ enabled: false }),
    updateProfile: vi.fn(),
  },
}));

vi.mock("@/api", () => ({
  default: {
    getInboxEvents: vi.fn().mockResolvedValue({ events: [] }),
    getPushMessages: vi.fn().mockResolvedValue({ pending_approvals: [] }),
  },
}));

vi.mock("@/stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } }),
}));

vi.mock("@/components/AgentSelector", () => ({
  default: ({ collapsed }: { collapsed?: boolean }) => (
    <div data-testid="agent-selector" data-collapsed={String(!!collapsed)} />
  ),
}));

vi.mock("@/plugins/registry/hooks", () => ({
  useMenuItems: () => [],
  useRoutes: () => [],
}));

vi.mock("@/plugins/registry/Slot", () => ({
  Slot: () => null,
}));

vi.mock("./registry/adapter", () => ({
  deriveOpenKeys: () => [],
  findMenuItem: () => undefined,
  flattenMenu: () => [],
  renderIcon: () => null,
  routeIdToPath: () => null,
  toAntdItems: () => [],
}));

// ── Helper ────────────────────────────────────────────────────────────────────

function renderSidebar(selectedKey = "core.chat") {
  return render(
    <ThemeProvider>
      <App>
        <MemoryRouter>
          <Sidebar selectedKey={selectedKey} />
        </MemoryRouter>
      </App>
    </ThemeProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Sidebar — collapse/expand toggle", () => {
  beforeEach(() => {
    localStorage.setItem("qwenpaw-theme", "light");
    // Ensure matchMedia returns false (desktop, non-mobile)
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => vi.clearAllMocks());

  it("renders the collapse toggle button", async () => {
    renderSidebar();
    // The collapse toggle button is always rendered
    await waitFor(() => {
      const buttons = screen.getAllByRole("button");
      expect(buttons.length).toBeGreaterThan(0);
    });
  });

  it("AgentSelector is visible (expanded state) before collapse", async () => {
    renderSidebar();
    await waitFor(() => {
      expect(screen.getByTestId("agent-selector")).toBeInTheDocument();
    });
    // In expanded state collapsed prop should be false
    expect(screen.getByTestId("agent-selector")).toHaveAttribute(
      "data-collapsed",
      "false",
    );
  });

  it("clicking the collapse toggle switches to collapsed nav (hides AgentSelector)", async () => {
    renderSidebar();

    // Wait for mount effects
    await waitFor(() => {
      expect(screen.getByTestId("agent-selector")).toBeInTheDocument();
    });

    // Find the collapse toggle — it carries the SparkMenuFoldLine icon in expanded state.
    // It is the last button in the Sider (collapseToggleContainer is at the bottom).
    const allButtons = screen.getAllByRole("button");
    const collapseBtn = allButtons[allButtons.length - 1];
    fireEvent.click(collapseBtn);

    // After collapse the AgentSelector should no longer be visible
    await waitFor(() => {
      expect(screen.queryByTestId("agent-selector")).not.toBeInTheDocument();
    });
  });

  it("clicking collapse twice returns to expanded state", async () => {
    renderSidebar();

    await waitFor(() => {
      expect(screen.getByTestId("agent-selector")).toBeInTheDocument();
    });

    // First click — collapse
    let allButtons = screen.getAllByRole("button");
    fireEvent.click(allButtons[allButtons.length - 1]);

    await waitFor(() => {
      expect(screen.queryByTestId("agent-selector")).not.toBeInTheDocument();
    });

    // Second click — expand; the collapsed nav renders buttons too, pick last
    allButtons = screen.getAllByRole("button");
    fireEvent.click(allButtons[allButtons.length - 1]);

    await waitFor(() => {
      expect(screen.getByTestId("agent-selector")).toBeInTheDocument();
    });
  });
});
