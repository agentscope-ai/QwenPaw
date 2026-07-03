import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ChatSessionDrawer from "./index";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";

// Mock react-window's VariableSizeList to render all items directly
// (jsdom has no layout, so the virtual list never renders rows).
// Must use forwardRef because the component uses ref={listRef} for resetAfterIndex.
const { MockVariableSizeList } = vi.hoisted(() => {
  const React = require("react");
  const MockVariableSizeList = React.forwardRef((props: any, ref: any) => {
    React.useImperativeHandle(ref, () => ({
      resetAfterIndex: () => {},
    }));
    const Row = props.children;
    return (
      <>
        {Array.from({ length: props.itemCount }, (_: any, i: number) => (
          <Row key={i} index={i} style={{}} data={props.itemData} />
        ))}
      </>
    );
  });
  return { MockVariableSizeList };
});
vi.mock("react-window", () => ({
  VariableSizeList: MockVariableSizeList,
}));

const {
  mockCreateSession,
  mockSetCurrentSessionId,
  mockSetSessions,
  mockDeleteChat,
  mockUpdateChat,
  mockGetSessionList,
  mockNavigate,
  mockGetEffectiveSessionId,
} = vi.hoisted(() => ({
  mockCreateSession: vi.fn().mockResolvedValue(undefined),
  mockSetCurrentSessionId: vi.fn(),
  mockSetSessions: vi.fn(),
  mockDeleteChat: vi.fn().mockResolvedValue(undefined),
  mockUpdateChat: vi.fn().mockResolvedValue(undefined),
  mockGetSessionList: vi.fn().mockResolvedValue([]),
  mockNavigate: vi.fn(),
  mockGetEffectiveSessionId: vi.fn((id: string) => id),
}));

vi.mock("@agentscope-ai/chat", () => ({
  useChatAnywhereSessionsState: vi.fn(() => ({
    sessions: [],
    currentSessionId: null,
    setCurrentSessionId: mockSetCurrentSessionId,
    setSessions: mockSetSessions,
  })),
  useChatAnywhereSessions: vi.fn(() => ({ createSession: mockCreateSession })),
}));

vi.mock("@/api/modules/chat", () => ({
  chatApi: { deleteChat: mockDeleteChat, updateChat: mockUpdateChat },
  sessionApi: {
    listChats: vi.fn(),
    createChat: vi.fn(),
    getChat: vi.fn(),
    updateChat: mockUpdateChat,
    deleteChat: mockDeleteChat,
    batchDeleteChats: vi.fn(),
    stopChat: vi.fn(),
  },
}));

vi.mock("../../sessionApi", () => ({
  default: {
    getSessionList: mockGetSessionList,
    isSessionSwitching: false,
    startNewSwitch: vi.fn(() => ({ signal: { aborted: false } })),
    preloadSession: vi.fn().mockResolvedValue({ session: {}, realId: null }),
    finishSessionSwitch: vi.fn(),
    lastNavigatedChatId: null,
    getEffectiveSessionId: mockGetEffectiveSessionId,
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

vi.mock("@agentscope-ai/design", () => ({
  IconButton: ({
    onClick,
    icon,
  }: {
    onClick?: () => void;
    icon: React.ReactNode;
  }) => <button onClick={onClick}>{icon}</button>,
}));

// Mock ResizeObserver so FixedSizeList gets a non-zero height and renders rows.
const mockResizeObserver = vi.fn().mockImplementation(function (
  this: unknown,
  callback: (entries: ResizeObserverEntry[]) => void,
) {
  return {
    observe: vi.fn((el: HTMLElement) => {
      callback([
        {
          target: el,
          contentRect: { height: 600 },
        } as unknown as ResizeObserverEntry,
      ]);
    }),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  };
});
(globalThis as any).ResizeObserver = mockResizeObserver;

// jsdom returns 0 for clientHeight; the drawer uses it as a fallback to
// set listHeight when ResizeObserver hasn't fired yet.
Object.defineProperty(HTMLElement.prototype, "clientHeight", {
  configurable: true,
  get(this: HTMLElement) {
    return 600;
  },
});

vi.mock("../ChatSessionItem", () => ({
  default: ({
    sessionId,
    name,
    onClick,
    onEdit,
    onDelete,
    onPin,
    onEditSubmit,
    onEditCancel,
  }: any) => (
    <div data-testid="session-item">
      <span onClick={() => onClick?.(sessionId)}>{name}</span>
      <button data-testid="edit-btn" onClick={() => onEdit?.(sessionId, name)}>
        edit
      </button>
      <button data-testid="delete-btn" onClick={() => onDelete?.(sessionId)}>
        delete
      </button>
      <button data-testid="pin-btn" onClick={() => onPin?.(sessionId)}>
        pin
      </button>
      <button data-testid="edit-submit-btn" onClick={onEditSubmit}>
        submit
      </button>
      <button data-testid="edit-cancel-btn" onClick={onEditCancel}>
        cancel
      </button>
    </div>
  ),
}));

vi.mock("../../../../Control/Channels/components", () => ({
  getChannelLabel: () => undefined,
  ChannelIcon: ({ channelKey }: { channelKey: string }) => (
    <span data-testid="channel-icon">{channelKey}</span>
  ),
}));

vi.mock("@agentscope-ai/icons", () => ({
  SparkOperateRightLine: () => (
    <span data-icon="SparkOperateRightLine">icon</span>
  ),
  SparkLockLine: () => <span data-testid="icon">lock</span>,
  SparkLockFill: () => <span data-testid="icon">lock-fill</span>,
  SparkDownArrowLine: ({ size }: { size?: number }) => (
    <span data-testid="icon">chevron-{size}</span>
  ),
}));

vi.mock("../../../../components/ContextMenu", () => ({
  ContextMenu: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  useContextMenu: () => ({ show: vi.fn(), hide: vi.fn() }),
}));

const defaultProps = { open: true, onClose: vi.fn() };

function withSession(overrides: Record<string, unknown> = {}) {
  // updatedAt ensures the session falls into the "today" group (not collapsed
  // by default). Without it, sessions without timestamps land in "older"
  // which is collapsed, causing them to not render in the virtual list.
  vi.mocked(useChatAnywhereSessionsState).mockReturnValue({
    sessions: [
      {
        id: "s1",
        name: "Session One",
        updatedAt: new Date().toISOString(),
        ...overrides,
      },
    ] as any,
    currentSessionId: null,
    setCurrentSessionId: mockSetCurrentSessionId,
    setSessions: mockSetSessions,
  } as any);
}

describe("ChatSessionDrawer", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders nothing when open=false", () => {
    renderWithProviders(<ChatSessionDrawer open={false} onClose={vi.fn()} />);
    expect(screen.queryByText("chat.allChats")).not.toBeInTheDocument();
  });

  it("renders title chat.allChats when open=true", () => {
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    expect(screen.getByText("chat.allChats")).toBeInTheDocument();
  });

  it("clicking new chat calls createSession", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(<ChatSessionDrawer open onClose={onClose} />);
    await user.click(screen.getByText("chat.createNewChat"));
    expect(mockCreateSession).toHaveBeenCalledOnce();
  });

  it("renders ChatSessionItem for each session", async () => {
    withSession();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByText("Session One")).toBeInTheDocument(),
    );
  });

  it("clicking a session item navigates to the session path", async () => {
    withSession();
    const user = userEvent.setup();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByText("Session One")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("Session One"));
    expect(mockNavigate).toHaveBeenCalledWith("/chat/s1");
  });

  it("clicking the close button calls onClose", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(<ChatSessionDrawer open onClose={onClose} />);
    await user.click(
      document
        .querySelector('[data-icon="SparkOperateRightLine"]')!
        .closest("button")!,
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("delete calls deleteChat with backend id and refreshes", async () => {
    withSession({ realId: "uuid-1" });
    const user = userEvent.setup();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByTestId("delete-btn")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("delete-btn"));
    expect(mockDeleteChat).toHaveBeenCalledWith("uuid-1");
    expect(mockGetSessionList).toHaveBeenCalled();
  });

  it("delete with numeric id skips deleteChat API", async () => {
    withSession({ id: "12345" });
    const user = userEvent.setup();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByTestId("delete-btn")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("delete-btn"));
    expect(mockDeleteChat).not.toHaveBeenCalled();
  });

  it("edit start sets editing state and edit submit calls updateChat", async () => {
    withSession({ realId: "uuid-1" });
    const user = userEvent.setup();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByTestId("edit-btn")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("edit-btn"));
    await user.click(screen.getByTestId("edit-submit-btn"));
    expect(mockUpdateChat).toHaveBeenCalledWith("uuid-1", {
      name: "Session One",
    });
  });

  it("edit cancel resets editing state without API call", async () => {
    withSession({ realId: "uuid-1" });
    const user = userEvent.setup();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByTestId("edit-btn")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("edit-btn"));
    await user.click(screen.getByTestId("edit-cancel-btn"));
    expect(mockUpdateChat).not.toHaveBeenCalled();
  });

  it("pin toggle calls updateChat with toggled pinned state", async () => {
    withSession({ realId: "uuid-1", pinned: false });
    const user = userEvent.setup();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await waitFor(() =>
      expect(screen.getByTestId("pin-btn")).toBeInTheDocument(),
    );
    await user.click(screen.getByTestId("pin-btn"));
    expect(mockUpdateChat).toHaveBeenCalledWith("uuid-1", { pinned: true });
  });

  it("on open=true triggers session list refresh", async () => {
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await vi.waitFor(() => expect(mockGetSessionList).toHaveBeenCalled());
  });

  it("pinned sessions sort before unpinned", async () => {
    vi.mocked(useChatAnywhereSessionsState).mockReturnValue({
      sessions: [
        { id: "s1", name: "Unpinned", updatedAt: new Date().toISOString() },
        {
          id: "s2",
          name: "Pinned",
          pinned: true,
          updatedAt: new Date().toISOString(),
        },
      ] as any,
      currentSessionId: null,
      setCurrentSessionId: mockSetCurrentSessionId,
      setSessions: mockSetSessions,
    } as any);
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    const items = await screen.findAllByTestId("session-item");
    expect(items[0]).toHaveTextContent("Pinned");
    expect(items[1]).toHaveTextContent("Unpinned");
  });
});
