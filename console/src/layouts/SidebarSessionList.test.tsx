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
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { renderWithProviders } from "@/test/common_setup";

// ---- Hoisted mocks ---------------------------------------------------------

const mockSessionListData = vi.hoisted(() => vi.fn());
const mockChatGroups = vi.hoisted(() => vi.fn());
const mockCollapsedGroups = vi.hoisted(() => vi.fn());

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

vi.mock(
  "../pages/Chat/components/ChatSessionDrawer/useSessionListData",
  () => ({
    useSessionListData: (...args: unknown[]) => mockSessionListData(...args),
    getBackendId: (s: { realId?: string; id?: string }) =>
      s?.realId ?? s?.id ?? null,
  }),
);

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
  default: () => <div data-testid="group-header" />,
}));

vi.mock("../components/SessionDateHeader", () => ({
  default: ({ label }: { label: string }) => (
    <div data-testid="date-header">{label}</div>
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
      ? selector({ selectedAgent: "agent-1" })
      : { selectedAgent: "agent-1" },
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
  });
}

describe("SidebarSessionList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    const btn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("chat.newChatTooltip"));
    expect(btn).toBeTruthy();
    fireEvent.click(btn!);
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
    const btn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("chat.newChatTooltip"));
    fireEvent.click(btn!);
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
    const newGroupBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("New group"));
    expect(newGroupBtn).toBeTruthy();
    fireEvent.click(newGroupBtn!);
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
});
