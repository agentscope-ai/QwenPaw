import { describe, it, expect, vi, afterEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ChatSessionDrawer from "./index";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";

const {
  mockCreateSession,
  mockSetCurrentSessionId,
  mockSetSessions,
  mockDeleteChat,
  mockUpdateChat,
  mockGetSessionList,
} = vi.hoisted(() => ({
  mockCreateSession: vi.fn().mockResolvedValue(undefined),
  mockSetCurrentSessionId: vi.fn(),
  mockSetSessions: vi.fn(),
  mockDeleteChat: vi.fn().mockResolvedValue(undefined),
  mockUpdateChat: vi.fn().mockResolvedValue(undefined),
  mockGetSessionList: vi.fn().mockResolvedValue([]),
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
  default: { getSessionList: mockGetSessionList },
}));

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

vi.mock("../../ChatSessionItem", () => ({
  default: ({ name, onClick, onEdit, onDelete }: any) => (
    <div data-testid="session-item">
      <span onClick={onClick}>{name}</span>
      <button data-testid="edit-btn" onClick={onEdit}>
        edit
      </button>
      <button data-testid="delete-btn" onClick={onDelete}>
        delete
      </button>
    </div>
  ),
}));

vi.mock("../../../../Control/Channels/components", () => ({
  getChannelLabel: () => undefined,
}));

const defaultProps = { open: true, onClose: vi.fn() };

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

  it("renders ChatSessionItem for each session", () => {
    vi.mocked(useChatAnywhereSessionsState).mockReturnValue({
      sessions: [{ id: "s1", name: "Session One" }] as any,
      currentSessionId: null,
      setCurrentSessionId: mockSetCurrentSessionId,
      setSessions: mockSetSessions,
    } as any);
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    expect(screen.getByText("Session One")).toBeInTheDocument();
  });

  it("clicking a session item calls setCurrentSessionId", async () => {
    vi.mocked(useChatAnywhereSessionsState).mockReturnValue({
      sessions: [{ id: "s1", name: "Session One" }] as any,
      currentSessionId: null,
      setCurrentSessionId: mockSetCurrentSessionId,
      setSessions: mockSetSessions,
    } as any);
    const user = userEvent.setup();
    renderWithProviders(<ChatSessionDrawer {...defaultProps} />);
    await user.click(screen.getByText("Session One"));
    expect(mockSetCurrentSessionId).toHaveBeenCalledWith("s1");
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
});
