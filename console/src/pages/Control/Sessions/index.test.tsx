// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import less from "less";
import type { ComponentProps, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import type { Session } from "./components";

const mockNavigate = vi.hoisted(() => vi.fn());
const mockUseSessions = vi.hoisted(() => vi.fn());
const mockListChannelTypes = vi.hoisted(() => vi.fn());
const mockForm = vi.hoisted(() => ({
  setFieldsValue: vi.fn(),
  submit: vi.fn(),
}));
const capturedTableProps = vi.hoisted<{
  value: Record<string, unknown> | null;
}>(() => ({ value: null }));
const capturedCardProps = vi.hoisted<{
  values: Array<Record<string, unknown>>;
}>(() => ({ values: [] }));
const capturedFilterBarProps = vi.hoisted<{
  isMobile?: boolean;
}>(() => ({}));
const stylesSource = readFileSync(
  join(process.cwd(), "src/pages/Control/Sessions/index.module.less"),
  "utf8",
);
const pageHeaderStylesSource = readFileSync(
  join(process.cwd(), "src/components/PageHeader/index.module.less"),
  "utf8",
);

function getActiveCss(css: string, width: number) {
  const source = document.createElement("style");
  source.textContent = css;
  document.head.appendChild(source);

  const activeRules = Array.from(source.sheet?.cssRules ?? []).flatMap(
    (rule) => {
      if (rule.type !== CSSRule.MEDIA_RULE) {
        return rule.cssText;
      }

      const mediaRule = rule as CSSMediaRule;
      const maxWidth = mediaRule.conditionText.match(/max-width:\s*(\d+)px/);
      if (!maxWidth || width > Number(maxWidth[1])) {
        return [];
      }
      return Array.from(mediaRule.cssRules, (nestedRule) => nestedRule.cssText);
    },
  );
  source.remove();
  return activeRules.join("\n");
}

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<object>("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options?.name ? `${key}:${String(options.name)}` : key,
  }),
}));

vi.mock("../../../api", () => ({
  default: { listChannelTypes: mockListChannelTypes },
}));

vi.mock("./useSessions", () => ({
  useSessions: () => mockUseSessions(),
}));

vi.mock("./components", () => ({
  FilterBar: ({
    isMobile,
    filterTitle,
    onTitleChange,
  }: {
    isMobile?: boolean;
    filterTitle: string;
    onTitleChange: (value: string) => void;
  }) => {
    capturedFilterBarProps.isMobile = isMobile;
    return (
      <input
        aria-label="title-filter"
        value={filterTitle}
        onChange={(event) => onTitleChange(event.target.value)}
      />
    );
  },
  SessionDrawer: () => null,
  formatTime: (value: unknown) => String(value ?? ""),
  useSessionColumns: () => [],
}));

vi.mock("@/components/PageHeader", () => ({
  PageHeader: ({
    className,
    extra,
  }: {
    className?: string;
    extra?: ReactNode;
  }) => <header className={className}>{extra}</header>,
}));

vi.mock("../Channels/components", () => ({
  ChannelIcon: () => <span data-testid="channel-icon" />,
}));

vi.mock("@agentscope-ai/design", () => ({
  Button: ({ children, onClick, ...props }: ComponentProps<"button">) => (
    <button type="button" onClick={onClick} {...props}>
      {children}
    </button>
  ),
  Card: ({ children, ...props }: { children?: ReactNode }) => {
    capturedCardProps.values.push(props);
    return <article data-testid="session-card">{children}</article>;
  },
  Checkbox: ({ checked, onChange, ...props }: ComponentProps<"input">) => (
    <input type="checkbox" checked={checked} onChange={onChange} {...props} />
  ),
  Form: Object.assign(
    ({ children }: { children?: ReactNode }) => <form>{children}</form>,
    { useForm: () => [mockForm] },
  ),
  Modal: { confirm: vi.fn() },
  Table: (props: Record<string, unknown>) => {
    capturedTableProps.value = props;
    return <div data-testid="sessions-table" />;
  },
  Tabs: ({
    items,
    onChange,
  }: {
    items: Array<{ key: string; label: ReactNode }>;
    onChange: (key: string) => void;
  }) => (
    <div role="tablist">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  ),
}));

import SessionsPage from "./index";

function createSessions(count: number): Session[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `session-${index}`,
    session_id: `console:user-${index}`,
    name: index === 25 ? "Chosen session" : `Session ${index}`,
    user_id: `user-${index}`,
    channel: "console",
    created_at: "2026-10-15T00:00:00Z",
    updated_at: "2026-10-15T00:00:00Z",
  }));
}

function setMatchMedia(matches: boolean) {
  window.matchMedia = vi.fn((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function setViewportWidth(width: number) {
  window.matchMedia = vi.fn((query: string) => ({
    matches: query === "(max-width: 1024px)" && width <= 1024,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function mockSessionsState(
  overrides: {
    sessions?: Session[];
    loading?: boolean;
    error?: Error | null;
    refreshSessions?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const sessions = overrides.sessions ?? [];
  mockUseSessions.mockReturnValue({
    agentId: "agent-1",
    sessions,
    loading: overrides.loading ?? false,
    error: overrides.error ?? null,
    refreshSessions: overrides.refreshSessions ?? vi.fn(),
    updateSession: vi.fn(),
    deleteSession: vi.fn(),
    batchDeleteSessions: vi.fn(),
    archiveSession: vi.fn(),
    unarchiveSession: vi.fn(),
    batchArchiveSessions: vi.fn(),
    batchUnarchiveSessions: vi.fn(),
    activeTab: "active",
    setActiveTab: vi.fn(),
    activeCount: sessions.filter((session) => !session.archived).length,
    archivedCount: sessions.filter((session) => session.archived).length,
  });
}

function mockSessions(count: number) {
  mockSessionsState({ sessions: createSessions(count) });
}

beforeEach(() => {
  vi.clearAllMocks();
  capturedTableProps.value = null;
  capturedCardProps.values = [];
  capturedFilterBarProps.isMobile = undefined;
  mockListChannelTypes.mockResolvedValue(["console"]);
  setMatchMedia(true);
});

afterEach(() => {
  setMatchMedia(false);
});

describe("SessionsPage mobile progressive rendering", () => {
  it("keeps the 600px header in one column after shared styles load", async () => {
    const { css } = await less.render(
      `${stylesSource}\n${pageHeaderStylesSource}`,
    );
    const activeStyles = document.createElement("style");
    activeStyles.textContent = getActiveCss(css, 600);
    document.head.appendChild(activeStyles);

    const fixture = document.createElement("div");
    fixture.className = "sessionsPage";
    fixture.innerHTML = `
      <header class="pageHeader">
        <div class="leading"></div>
        <div class="extra"></div>
      </header>
    `;
    document.body.appendChild(fixture);

    const [leading, extra] = Array.from(
      fixture.querySelectorAll<HTMLElement>(".pageHeader > div"),
    );
    expect(getComputedStyle(leading).gridColumn).toBe("1");
    expect(getComputedStyle(leading).gridRow).toBe("auto");
    expect(getComputedStyle(extra).gridColumn).toBe("1");
    expect(getComputedStyle(extra).gridRow).toBe("auto");

    fixture.remove();
    activeStyles.remove();
  });

  it("keeps the compact table fallback in the route stylesheet", () => {
    const compactStart = stylesSource.indexOf("@media (max-width: 1024px)");
    const compactRules = stylesSource.slice(compactStart);

    expect(compactStart).toBeGreaterThanOrEqual(0);
    expect(compactRules).toContain(".sessionsPage .pageHeader {");
    expect(compactRules).toContain("display: grid;");
    expect(compactRules).toContain("grid-template-columns: minmax(0, 1fr);");
    expect(compactRules).toContain(".tableCard {");
    expect(compactRules).toContain("display: none;");
  });

  it.each([
    { width: 390, compact: true },
    { width: 600, compact: true },
    { width: 820, compact: true },
    { width: 1024, compact: true },
    { width: 1025, compact: false },
    { width: 1280, compact: false },
  ])(
    "uses the expected responsive layout at $width px",
    async ({ width, compact }) => {
      setViewportWidth(width);
      mockSessions(2);
      renderWithProviders(<SessionsPage />);

      if (compact) {
        await waitFor(() =>
          expect(screen.getAllByTestId("session-card")).toHaveLength(2),
        );
        expect(screen.queryByTestId("sessions-table")).toBeNull();
      } else {
        await waitFor(() =>
          expect(screen.getByTestId("sessions-table")).toBeTruthy(),
        );
        expect(screen.getAllByTestId("session-card")).toHaveLength(1);
      }
      expect(capturedFilterBarProps.isMobile).toBe(compact);
      expect(document.querySelector("header")?.className).toBeTruthy();
      expect(window.matchMedia).toHaveBeenCalledWith("(max-width: 1024px)");
    },
  );

  it.each([390, 820])(
    "shows compact loading feedback at %i px",
    async (width) => {
      setViewportWidth(width);
      mockSessionsState({ loading: true });

      renderWithProviders(<SessionsPage />);

      expect(await screen.findByRole("status")).toHaveTextContent(
        "sessions.loading",
      );
      expect(screen.queryByTestId("session-card")).toBeNull();
      expect(screen.queryByTestId("sessions-table")).toBeNull();
    },
  );

  it.each([390, 820])(
    "recovers a rejected compact list at %i px without losing filters",
    async (width) => {
      setViewportWidth(width);
      const refreshSessions = vi.fn();
      mockSessionsState({
        error: new Error("list failed"),
        refreshSessions,
      });
      const view = renderWithProviders(<SessionsPage />);

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("sessions.loadFailed");
      fireEvent.change(screen.getByRole("textbox", { name: "title-filter" }), {
        target: { value: "Chosen" },
      });
      fireEvent.click(
        within(alert).getByRole("button", { name: "common.retry" }),
      );
      expect(refreshSessions).toHaveBeenCalledOnce();

      const recoveredSessions = createSessions(26);
      mockSessionsState({ sessions: recoveredSessions, refreshSessions });
      view.rerender(<SessionsPage />);

      await waitFor(() =>
        expect(screen.getAllByTestId("session-card")).toHaveLength(1),
      );
      expect(screen.getByText("Chosen session")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).toBeNull();
    },
  );

  it("does not present a successful empty compact list as an error", () => {
    mockSessions(0);
    renderWithProviders(<SessionsPage />);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it.each([500, 2000])(
    "bounds the first mobile render for %i sessions",
    async (count) => {
      mockSessions(count);
      renderWithProviders(<SessionsPage />);

      await waitFor(() => {
        expect(screen.getAllByTestId("session-card")).toHaveLength(20);
      });
      expect(
        screen.getByRole("button", { name: "common.loadMore" }),
      ).toBeTruthy();
    },
  );

  it("keeps selection and actions correct after loading and filtering", async () => {
    mockSessions(500);
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId("session-card")).toHaveLength(20);
    });
    fireEvent.click(screen.getByRole("button", { name: "common.loadMore" }));
    expect(screen.getAllByTestId("session-card")).toHaveLength(40);

    const chosenCard = screen
      .getAllByTestId("session-card")
      .find((card) => within(card).queryByText("Chosen session"));
    expect(chosenCard).toBeTruthy();

    fireEvent.click(
      within(chosenCard!).getByRole("checkbox", {
        name: "sessions.selectSession:Chosen session",
      }),
    );
    expect(
      screen.getByRole("button", { name: "sessions.archive.batchAction (1)" }),
    ).toBeTruthy();

    fireEvent.click(
      within(chosenCard!).getByRole("button", { name: "common.view" }),
    );
    expect(mockNavigate).toHaveBeenCalledWith("/chat/session-25");

    fireEvent.change(screen.getByRole("textbox", { name: "title-filter" }), {
      target: { value: "Chosen" },
    });
    await waitFor(() => {
      expect(screen.getAllByTestId("session-card")).toHaveLength(1);
    });
    expect(
      screen.getByRole("checkbox", {
        name: "sessions.selectSession:Chosen session",
      }),
    ).toBeChecked();
    expect(
      screen.getByRole("button", { name: "sessions.archive.batchAction (1)" }),
    ).toBeTruthy();
  });

  it("keeps the desktop table page size at ten", async () => {
    setMatchMedia(false);
    mockSessions(500);
    renderWithProviders(<SessionsPage />);

    await waitFor(() =>
      expect(screen.getByTestId("sessions-table")).toBeTruthy(),
    );
    expect(capturedTableProps.value?.pagination).toEqual({
      pageSize: 10,
      showSizeChanger: false,
    });
    expect(capturedCardProps.values).toContainEqual(
      expect.objectContaining({ styles: { body: { padding: 0 } } }),
    );
    expect(capturedCardProps.values[0]).not.toHaveProperty("bodyStyle");

    const rowSelection = capturedTableProps.value?.rowSelection as {
      onChange: (keys: React.Key[]) => void;
      selectedRowKeys: React.Key[];
    };
    act(() => rowSelection.onChange(["session-1"]));

    await waitFor(() => {
      const currentSelection = capturedTableProps.value?.rowSelection as {
        selectedRowKeys: React.Key[];
      };
      expect(currentSelection.selectedRowKeys).toEqual(["session-1"]);
    });
  });
});
