// @vitest-environment jsdom
/**
 * SidebarSessionList render tests — regression family: session state ×
 * navigation combos (bug_insights highest-frequency cluster, ~15 bugs)
 * and cross-agent switch isolation.
 *
 * Strategy: stub VariableSizeList to render every row directly (jsdom has
 * no layout engine, so the real virtualized list renders nothing), and
 * stub the DnD wrappers as pass-throughs. Heavy hooks are mocked so the
 * row-rendering logic (VirtualRow / GroupHeaderContent / date headers)
 * executes under test.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { renderWithProviders } from "@/test/common_setup";

// ---- Hoisted mocks ---------------------------------------------------------

const mockSessionListData = vi.hoisted(() => vi.fn());
const mockChatGroups = vi.hoisted(() => vi.fn());
const mockCollapsedGroups = vi.hoisted(() => vi.fn());
const mockSelectedAgent = vi.hoisted(() => ({ current: "agent-1" }));
/** Captures the latest virtual-list props so tests can assert row heights. */
const mockListProps = vi.hoisted(() => ({
  current: null as null | {
    itemCount: number;
    itemSize: (index: number) => number;
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: "en" },
  }),
}));

// react-window: render ALL rows so row logic is covered
vi.mock("react-window", () => ({
  VariableSizeList: React.forwardRef(
    (
      props: {
        itemCount: number;
        itemSize: (index: number) => number;
        itemData: unknown;
        children: React.ComponentType<{
          index: number;
          style?: object;
          data: unknown;
        }>;
      },
      ref: React.Ref<object>,
    ) => {
      React.useImperativeHandle(ref, () => ({
        scrollTo: vi.fn(),
        scrollToItem: vi.fn(),
        resetAfterIndex: vi.fn(),
      }));
      mockListProps.current = {
        itemCount: props.itemCount,
        itemSize: props.itemSize,
      };
      const Row = props.children;
      return (
        <div data-testid="virtual-list">
          {Array.from({ length: props.itemCount }, (_, i) => (
            <Row key={i} index={i} data={props.itemData} style={{}} />
          ))}
        </div>
      );
    },
  ),
}));

// DnD wrappers as pass-throughs
vi.mock("../components/SessionGroupDnd", () => ({
  SessionGroupDndProvider: ({ children }: { children?: React.ReactNode }) => (
    <>{children}</>
  ),
  DraggableSession: ({ children }: { children?: React.ReactNode }) => (
    <>{children}</>
  ),
  SessionDropZone: ({ children }: { children?: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("./useSidebarSessionListData", () => ({
  useSessionListData: (...args: unknown[]) => mockSessionListData(...args),
  getBackendId: (s: { realId?: string; id?: string }) =>
    s?.realId ?? s?.id ?? null,
}));

vi.mock("../hooks/useChatGroups", () => ({
  useChatGroups: () => mockChatGroups(),
}));

vi.mock("../hooks/useCollapsedChatGroups", () => ({
  useCollapsedChatGroups: () => mockCollapsedGroups(),
}));

vi.mock("../hooks/useRevealActiveChatGroup", () => ({
  useRevealActiveChatGroup: vi.fn(),
}));

vi.mock("../hooks/useSessionAttention", () => ({
  useSessionAttention: () => new Set<string>(),
}));

vi.mock("../components/SessionItem", () => ({
  default: ({
    name,
    sessionId,
    onClick,
  }: {
    name: string;
    sessionId: string;
    onClick: (id: string) => void;
  }) => (
    <button
      data-testid={`session-item-${sessionId}`}
      onClick={() => onClick(sessionId)}
    >
      {name}
    </button>
  ),
}));

vi.mock("../components/SessionGroupHeader", () => ({
  default: ({
    group,
    count,
    collapsed,
    onToggle,
  }: {
    group: { id: string; name: string };
    count: number;
    collapsed: boolean;
    onToggle: () => void;
  }) => (
    <button
      type="button"
      data-testid={`group-header-${group.id}`}
      aria-expanded={!collapsed}
      onClick={onToggle}
    >
      {group.name} {count}
    </button>
  ),
}));

vi.mock("../pages/Control/Channels/components", () => ({
  getChannelLabel: (key: string) => `channel:${key}`,
}));

vi.mock("../api/modules/chat", () => ({
  chatApi: { updateChat: vi.fn().mockResolvedValue({}) },
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

vi.mock("../stores/agentStore", () => ({
  useAgentStore: (selector?: (s: { selectedAgent: string }) => unknown) =>
    selector
      ? selector({ selectedAgent: mockSelectedAgent.current })
      : { selectedAgent: mockSelectedAgent.current },
}));

vi.mock("../stores/sessionListStore", () => ({
  useSessionListStore: (selector?: (s: { sessions: unknown[] }) => unknown) =>
    selector ? selector({ sessions: [] }) : { sessions: [] },
  syncSessionsGlobal: vi.fn(),
}));

import SidebarSessionList from "./SidebarSessionList";

// ---- Fixtures --------------------------------------------------------------

const sessionA = {
  id: "sess-a",
  name: "Alpha Chat",
  status: "idle",
  generating: false,
  archived: false,
  pinned: false,
  updatedAt: new Date().toISOString(),
  channel: "",
};

const sessionB = {
  id: "sess-b",
  name: "Beta Report",
  status: "running",
  generating: true,
  archived: false,
  pinned: false,
  updatedAt: new Date().toISOString(),
  channel: "wechat",
};

function mockData(
  sessions: unknown[],
  overrides: Record<string, unknown> = {},
) {
  // Forward the injected onSessionClick through the mocked hook so click
  // routing tests observe it.
  mockSessionListData.mockImplementation(
    (
      _store: unknown,
      _set: unknown,
      options?: { onSessionClick?: (id: string) => void },
    ) => ({
      sortedSessions: sessions,
      loading: false,
      editingSessionId: null,
      editValue: "",
      handleSessionClick: (id: string) => options?.onSessionClick?.(id),
      handleEditStart: vi.fn(),
      handleDelete: vi.fn(),
      handleArchiveToggle: vi.fn(),
      handlePinToggle: vi.fn(),
      handleEditChange: vi.fn(),
      handleEditSubmit: vi.fn(),
      handleEditCancel: vi.fn(),
      refreshSessions: vi.fn().mockResolvedValue(undefined),
      ...overrides,
    }),
  );
  mockChatGroups.mockReturnValue({
    // groupChats only emits rows for groups that exist — provide the
    // default "Uncategorized" group so unassigned sessions render.
    groups: [
      {
        id: "default",
        name: "Uncategorized",
        order: 0,
        kind: "default",
        pinned: false,
      },
    ],
    createGroup: vi.fn().mockResolvedValue({ id: "g-new" }),
    renameGroup: vi.fn(),
    pinGroup: vi.fn(),
    deleteGroup: vi.fn(),
    reorderGroups: vi.fn(),
  });
  mockCollapsedGroups.mockReturnValue({
    collapsedGroups: new Set<string>(),
    toggleGroup: vi.fn(),
    expandGroup: vi.fn(),
    initializeCollapsedGroups: vi.fn(),
  });
}

describe("SidebarSessionList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockSelectedAgent.current = "agent-1";
    // The virtual list only renders once the wrapper has a measured height.
    // jsdom reports clientHeight=0, so make ResizeObserver report one
    // immediately on observe. Must be a function (constructible), not an
    // arrow fn.
    global.ResizeObserver = vi.fn().mockImplementation(function (
      this: unknown,
      cb: (entries: { contentRect: { height: number } }[]) => void,
    ) {
      return {
        observe: () => cb([{ contentRect: { height: 600 } }]),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
      };
    }) as unknown as typeof ResizeObserver;
  });

  it("renders the empty state when there are no conversations", async () => {
    mockData([]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByText("No conversations")).toBeTruthy();
    });
  });

  it("renders session rows via the (stubbed) virtual list", async () => {
    mockData([sessionA, sessionB]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("virtual-list")).toBeTruthy();
    });
    expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    expect(screen.getByTestId("session-item-sess-b")).toBeTruthy();
  });

  it("initializes older unpinned groups as collapsed", async () => {
    const initializeCollapsedGroups = vi.fn();
    mockData([sessionA, { ...sessionB, groupId: "work" }]);
    mockCollapsedGroups.mockReturnValue({
      collapsedGroups: new Set<string>(),
      toggleGroup: vi.fn(),
      expandGroup: vi.fn(),
      initializeCollapsedGroups,
    });
    mockChatGroups.mockReturnValue({
      groups: [
        {
          id: "default",
          name: "Uncategorized",
          order: 0,
          kind: "default",
          pinned: false,
        },
        {
          id: "work",
          name: "Work",
          order: 1,
          kind: "custom",
          pinned: false,
        },
        {
          id: "older",
          name: "Older",
          order: 2,
          kind: "custom",
          pinned: true,
        },
        {
          id: "archive",
          name: "Archive",
          order: 3,
          kind: "custom",
          pinned: false,
        },
      ],
      createGroup: vi.fn().mockResolvedValue({ id: "g-new" }),
      renameGroup: vi.fn(),
      pinGroup: vi.fn(),
      deleteGroup: vi.fn(),
      reorderGroups: vi.fn(),
    });
    renderWithProviders(<SidebarSessionList />);

    await waitFor(() => expect(initializeCollapsedGroups).toHaveBeenCalled());
    expect(initializeCollapsedGroups).toHaveBeenCalledWith(
      new Set(["archive"]),
    );
  });

  it("keeps the active group expanded during default initialization", async () => {
    const initializeCollapsedGroups = vi.fn();
    const now = Date.now();
    mockData([
      { ...sessionA, updatedAt: new Date(now).toISOString() },
      {
        ...sessionB,
        groupId: "work",
        updatedAt: new Date(now - 1000).toISOString(),
      },
      {
        ...sessionA,
        id: "older-active",
        groupId: "older",
        updatedAt: new Date(now - 2000).toISOString(),
      },
    ]);
    mockCollapsedGroups.mockReturnValue({
      collapsedGroups: new Set<string>(),
      toggleGroup: vi.fn(),
      expandGroup: vi.fn(),
      initializeCollapsedGroups,
    });
    mockChatGroups.mockReturnValue({
      groups: [
        {
          id: "default",
          name: "Uncategorized",
          order: 0,
          kind: "default",
          pinned: false,
        },
        {
          id: "work",
          name: "Work",
          order: 1,
          kind: "custom",
          pinned: false,
        },
        {
          id: "older",
          name: "Older",
          order: 2,
          kind: "custom",
          pinned: false,
        },
        {
          id: "archive",
          name: "Archive",
          order: 3,
          kind: "custom",
          pinned: false,
        },
      ],
      createGroup: vi.fn().mockResolvedValue({ id: "g-new" }),
      renameGroup: vi.fn(),
      pinGroup: vi.fn(),
      deleteGroup: vi.fn(),
      reorderGroups: vi.fn(),
    });

    renderWithProviders(<SidebarSessionList />, {
      initialEntries: ["/chat/older-active"],
    });

    await waitFor(() => expect(initializeCollapsedGroups).toHaveBeenCalled());
    expect(initializeCollapsedGroups).toHaveBeenCalledWith(
      new Set(["archive"]),
    );
  });

  it("renders every conversation without a load-more control", async () => {
    const sessions = Array.from({ length: 12 }, (_, index) => ({
      ...sessionA,
      id: `session-${index + 1}`,
      name: `Conversation ${index + 1}`,
      updatedAt: new Date(Date.now() - index * 1000).toISOString(),
    }));
    mockData(sessions);
    renderWithProviders(<SidebarSessionList />);

    await waitFor(() => {
      expect(screen.getByTestId("session-item-session-12")).toBeTruthy();
    });
    expect(screen.getByTestId("session-item-session-11")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Load more/ })).toBeNull();
  });

  it("reveals an active unpinned conversation after ten pinned ones", async () => {
    const pinnedSessions = Array.from({ length: 10 }, (_, index) => ({
      ...sessionA,
      id: `pinned-${index + 1}`,
      name: `Pinned ${index + 1}`,
      pinned: true,
      updatedAt: new Date(Date.now() - (index + 1) * 1000).toISOString(),
    }));
    const activeSession = {
      ...sessionA,
      id: "active-session",
      name: "Active conversation",
      pinned: false,
      updatedAt: new Date().toISOString(),
    };
    mockData([activeSession, ...pinnedSessions]);

    renderWithProviders(<SidebarSessionList />, {
      initialEntries: ["/chat/active-session"],
    });

    await waitFor(() => {
      expect(screen.getByTestId("session-item-active-session")).toBeTruthy();
    });
  });

  it("renders the full history around the active conversation", async () => {
    const sessions = Array.from({ length: 25 }, (_, index) => ({
      ...sessionA,
      id: `session-${index + 1}`,
      name: `Conversation ${index + 1}`,
      updatedAt: new Date(Date.now() - index * 1000).toISOString(),
    }));
    mockData(sessions);
    renderWithProviders(<SidebarSessionList />, {
      initialEntries: ["/chat/session-12"],
    });

    await waitFor(() => {
      expect(screen.getByTestId("session-item-session-12")).toBeTruthy();
    });
    expect(screen.getByTestId("session-item-session-21")).toBeTruthy();
    expect(screen.getByTestId("session-item-session-25")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Load more/ })).toBeNull();
  });

  it("swaps the rendered list when switching agents", async () => {
    const agentOneSessions = Array.from({ length: 25 }, (_, index) => ({
      ...sessionA,
      id: `agent-one-${index + 1}`,
      name: `Agent one ${index + 1}`,
      updatedAt: new Date(Date.now() - index * 1000).toISOString(),
    }));
    const agentTwoSessions = Array.from({ length: 25 }, (_, index) => ({
      ...sessionA,
      id: `agent-two-${index + 1}`,
      name: `Agent two ${index + 1}`,
      updatedAt: new Date(Date.now() - index * 1000).toISOString(),
    }));

    mockData(agentOneSessions);
    const { rerender } = renderWithProviders(<SidebarSessionList />);

    await waitFor(() => {
      expect(screen.getByTestId("session-item-agent-one-25")).toBeTruthy();
    });

    mockSelectedAgent.current = "agent-2";
    mockData(agentTwoSessions);
    rerender(<SidebarSessionList />);

    await waitFor(() => {
      expect(screen.getByTestId("session-item-agent-two-25")).toBeTruthy();
      expect(screen.queryByTestId("session-item-agent-one-1")).toBeNull();
    });
  });

  it("shows all matching conversations while searching", async () => {
    const sessions = Array.from({ length: 12 }, (_, index) => ({
      ...sessionA,
      id: `session-${index + 1}`,
      name: `Conversation ${index + 1}`,
      updatedAt: new Date(Date.now() - index * 1000).toISOString(),
    }));
    mockData(sessions);
    renderWithProviders(<SidebarSessionList />);

    await waitFor(() => {
      expect(screen.getByTestId("session-item-session-11")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(await screen.findByText("Search conversations"));
    fireEvent.change(screen.getByPlaceholderText("Search…"), {
      target: { value: "Conversation 1" },
    });

    await waitFor(() => {
      expect(screen.queryByTestId("session-item-session-2")).toBeNull();
    });
    expect(screen.getByTestId("session-item-session-11")).toBeTruthy();
    expect(screen.getByTestId("session-item-session-12")).toBeTruthy();
  });

  it("routes session clicks through the injected callback", async () => {
    const onSessionClick = vi.fn();
    mockData([sessionA]);
    renderWithProviders(<SidebarSessionList onSessionClick={onSessionClick} />);
    await waitFor(() => {
      expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("session-item-sess-a"));
    expect(onSessionClick).toHaveBeenCalledWith("sess-a");
  });

  it("dispatches a DOM event when no click handler is injected", async () => {
    const received: unknown[] = [];
    const listener = (e: Event) => received.push((e as CustomEvent).detail);
    window.addEventListener("qwenpaw:sidebar-select-session", listener);
    mockData([sessionA]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("session-item-sess-a"));
    expect(received).toEqual([{ sessionId: "sess-a" }]);
    window.removeEventListener("qwenpaw:sidebar-select-session", listener);
  });

  it("creates a new chat via the injected callback", async () => {
    const onNewChat = vi.fn();
    mockData([]);
    renderWithProviders(<SidebarSessionList onNewChat={onNewChat} />);
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    expect(onNewChat).toHaveBeenCalled();
  });

  it("dispatches a new-chat DOM event when no handler is injected", async () => {
    let fired = false;
    const listener = () => {
      fired = true;
    };
    window.addEventListener("qwenpaw:sidebar-new-chat", listener);
    mockData([]);
    renderWithProviders(<SidebarSessionList />);
    fireEvent.click(screen.getByRole("button", { name: "New task" }));
    expect(fired).toBe(true);
    window.removeEventListener("qwenpaw:sidebar-new-chat", listener);
  });

  it("collapses and expands the conversation history section", async () => {
    mockData([sessionA]);
    renderWithProviders(<SidebarSessionList />);
    const historyBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("Conversation History"));
    expect(historyBtn).toBeTruthy();
    fireEvent.click(historyBtn!);
    // Collapsed: search input disappears
    await waitFor(() => {
      expect(screen.queryByTestId("virtual-list")).toBeNull();
    });
    // Expand again
    fireEvent.click(historyBtn!);
    await waitFor(() => {
      expect(screen.getByTestId("virtual-list")).toBeTruthy();
    });
  });

  it("filters sessions by the search query", async () => {
    mockData([sessionA, sessionB]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(await screen.findByText("Search conversations"));
    const search = screen.getByPlaceholderText("Search…");
    fireEvent.change(search, { target: { value: "beta" } });
    await waitFor(() => {
      expect(screen.queryByTestId("session-item-sess-a")).toBeNull();
      expect(screen.getByTestId("session-item-sess-b")).toBeTruthy();
    });
  });

  it("opens the new-group input and creates a group on Enter", async () => {
    const createGroup = vi.fn().mockResolvedValue({ id: "g-new" });
    mockData([sessionA]);
    mockChatGroups.mockReturnValue({
      groups: [
        {
          id: "default",
          name: "Uncategorized",
          order: 0,
          kind: "default",
          pinned: false,
        },
      ],
      createGroup,
      renameGroup: vi.fn(),
      pinGroup: vi.fn(),
      deleteGroup: vi.fn(),
      reorderGroups: vi.fn(),
    });
    renderWithProviders(<SidebarSessionList />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.click(await screen.findByText("New group"));
    const input = screen.getByPlaceholderText("Group name");
    fireEvent.change(input, { target: { value: "My Group" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    await waitFor(() => {
      expect(createGroup).toHaveBeenCalledWith("My Group");
    });
  });

  it("shows the loading spinner while the first load is in flight", async () => {
    mockData([], { loading: true });
    renderWithProviders(<SidebarSessionList />);
    // Loading state renders the Spin (no sessions yet)
    await waitFor(() => {
      expect(screen.queryByText("No conversations")).toBeNull();
    });
  });

  it("renders group sections by default", async () => {
    mockData([sessionA, sessionB]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("group-header-default")).toBeTruthy();
    });
    expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    expect(screen.getByTestId("session-item-sess-b")).toBeTruthy();
  });

  it("renders a flat list in none mode", async () => {
    localStorage.setItem("qwenpaw_session_group_mode", "none");
    mockData([sessionA, sessionB]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    });
    expect(screen.queryByTestId("group-header-default")).toBeNull();
    expect(screen.getByTestId("session-item-sess-b")).toBeTruthy();
  });

  it("switches the grouping mode from the more menu and persists it", async () => {
    mockData([sessionA, sessionB]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("group-header-default")).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.mouseEnter(await screen.findByText("Group by"));
    fireEvent.click(await screen.findByText("No grouping"));

    await waitFor(() => {
      expect(screen.queryByTestId("group-header-default")).toBeNull();
    });
    expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    expect(localStorage.getItem("qwenpaw_session_group_mode")).toBe("none");
  });

  it("restores the chosen grouping mode after a remount", async () => {
    localStorage.setItem("qwenpaw_session_group_mode", "none");
    mockData([sessionA]);
    const { unmount } = renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    });
    unmount();

    mockData([sessionA]);
    renderWithProviders(<SidebarSessionList />);
    await waitFor(() => {
      expect(screen.getByTestId("session-item-sess-a")).toBeTruthy();
    });
    expect(screen.queryByTestId("group-header-default")).toBeNull();
  });

  describe("compact density row heights", () => {
    function setCompactViewport(compact: boolean) {
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: query.includes("max-height") ? compact : false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })) as unknown as typeof window.matchMedia;
    }

    function conversationFixture(count: number) {
      return Array.from({ length: count }, (_, index) => ({
        ...sessionA,
        id: `session-${index + 1}`,
        name: `Conversation ${index + 1}`,
        updatedAt: new Date(Date.now() - index * 1000).toISOString(),
      }));
    }

    afterEach(() => {
      setCompactViewport(false);
    });

    it("keeps full row metrics on tall viewports", async () => {
      localStorage.setItem("qwenpaw_session_group_mode", "source");
      mockData(conversationFixture(12));
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("virtual-list")).toBeTruthy();
      });
      const list = mockListProps.current;
      expect(list).toBeTruthy();
      // rows: groupHeader(default, 12) followed by all 12 sessions
      expect(list!.itemSize(0)).toBe(42);
      expect(list!.itemSize(1)).toBe(42);
      expect(list!.itemSize(11)).toBe(42);
    });

    it("compacts group headers and sessions on short viewports", async () => {
      setCompactViewport(true);
      localStorage.setItem("qwenpaw_session_group_mode", "source");
      mockData(conversationFixture(12));
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("virtual-list")).toBeTruthy();
      });
      const list = mockListProps.current!;
      expect(list.itemSize(0)).toBe(32);
      expect(list.itemSize(1)).toBe(30);
      expect(list.itemSize(11)).toBe(30);
    });

    it("compacts session rows in none mode on short viewports", async () => {
      setCompactViewport(true);
      localStorage.setItem("qwenpaw_session_group_mode", "none");
      mockData([sessionA]);
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("virtual-list")).toBeTruthy();
      });
      const list = mockListProps.current!;
      // single flat section: the first row is already a session
      expect(list.itemSize(0)).toBe(30);
    });

    function addEmptyCronGroup() {
      mockChatGroups.mockReturnValue({
        groups: [
          {
            id: "default",
            name: "Uncategorized",
            order: 0,
            kind: "default",
            pinned: false,
          },
          {
            id: "cron",
            name: "Scheduled tasks",
            order: 1,
            kind: "cron",
            pinned: false,
          },
        ],
        createGroup: vi.fn().mockResolvedValue({ id: "g-new" }),
        renameGroup: vi.fn(),
        pinGroup: vi.fn(),
        deleteGroup: vi.fn(),
        reorderGroups: vi.fn(),
      });
    }

    it("slims empty group headers on short viewports", async () => {
      setCompactViewport(true);
      localStorage.setItem("qwenpaw_session_group_mode", "source");
      mockData([sessionA]);
      addEmptyCronGroup();
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("group-header-cron")).toBeTruthy();
      });
      const list = mockListProps.current!;
      // rows: groupHeader(default, 1), session, groupHeader(cron, 0)
      expect(list.itemSize(0)).toBe(32);
      expect(list.itemSize(2)).toBe(24);
    });

    it("keeps empty group headers full height on tall viewports", async () => {
      localStorage.setItem("qwenpaw_session_group_mode", "source");
      mockData([sessionA]);
      addEmptyCronGroup();
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("group-header-cron")).toBeTruthy();
      });
      const list = mockListProps.current!;
      expect(list.itemSize(0)).toBe(42);
      expect(list.itemSize(2)).toBe(42);
    });
  });

  describe("activity range filter", () => {
    function datedSession(id: string, daysAgo: number) {
      return {
        ...sessionA,
        id,
        name: `Session ${id}`,
        updatedAt: new Date(Date.now() - daysAgo * 86_400_000).toISOString(),
      };
    }

    async function pickActivityRange(optionText: string) {
      fireEvent.click(screen.getByRole("button", { name: "More" }));
      fireEvent.mouseEnter(await screen.findByText("Activity range"));
      fireEvent.click(await screen.findByText(optionText));
    }

    it("narrows the list to today's conversations", async () => {
      mockData([datedSession("s-today", 0), datedSession("s-old", 40)]);
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("session-item-s-old")).toBeTruthy();
      });

      await pickActivityRange("Today");

      await waitFor(() => {
        expect(screen.queryByTestId("session-item-s-old")).toBeNull();
      });
      expect(screen.getByTestId("session-item-s-today")).toBeTruthy();
      expect(localStorage.getItem("qwenpaw_session_activity_filter")).toBe(
        "today",
      );
    });

    it("keeps conversations within 7 days", async () => {
      mockData([datedSession("s-week", 3), datedSession("s-old", 40)]);
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("session-item-s-old")).toBeTruthy();
      });

      await pickActivityRange("7 days");

      await waitFor(() => {
        expect(screen.queryByTestId("session-item-s-old")).toBeNull();
      });
      expect(screen.getByTestId("session-item-s-week")).toBeTruthy();
    });

    it("widens back to all conversations", async () => {
      localStorage.setItem("qwenpaw_session_activity_filter", "today");
      mockData([datedSession("s-today", 0), datedSession("s-old", 40)]);
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("session-item-s-today")).toBeTruthy();
      });
      expect(screen.queryByTestId("session-item-s-old")).toBeNull();

      await pickActivityRange("All");

      await waitFor(() => {
        expect(screen.getByTestId("session-item-s-old")).toBeTruthy();
      });
    });

    it("restores the persisted range after a remount", async () => {
      localStorage.setItem("qwenpaw_session_activity_filter", "today");
      mockData([datedSession("s-today", 0), datedSession("s-old", 40)]);
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("session-item-s-today")).toBeTruthy();
      });
      expect(screen.queryByTestId("session-item-s-old")).toBeNull();
    });

    it("shows a no-matching state when the range excludes everything", async () => {
      mockData([datedSession("s-old", 40)]);
      renderWithProviders(<SidebarSessionList />);
      await waitFor(() => {
        expect(screen.getByTestId("session-item-s-old")).toBeTruthy();
      });

      await pickActivityRange("Today");

      await waitFor(() => {
        expect(screen.getByText("No matching conversations")).toBeTruthy();
      });
    });
  });
});
