import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChatSessionDrawer from "./index";

const {
  mockCreateSession,
  mockGetEffectiveSessionId,
  mockNavigate,
  mockUseIsMobile,
} = vi.hoisted(() => ({
  mockCreateSession: vi.fn<() => Promise<void>>(),
  mockGetEffectiveSessionId: vi.fn((sessionId: string) => sessionId),
  mockNavigate: vi.fn(),
  mockUseIsMobile: vi.fn(() => true),
}));

vi.mock("antd", () => ({
  Drawer: ({
    children,
    onClose,
    open,
    width,
  }: {
    children: React.ReactNode;
    onClose: () => void;
    open: boolean;
    width: string | number;
  }) =>
    open ? (
      <div data-testid="drawer" data-width={width}>
        <button type="button" onClick={onClose}>
          drawer-close
        </button>
        {children}
      </div>
    ) : null,
}));

vi.mock("../../../../layouts/SidebarSessionList", () => ({
  default: ({
    onClose,
    onNewChat,
    onSessionClick,
  }: {
    onClose: () => void;
    onNewChat: () => void;
    onSessionClick: (sessionId: string) => void;
  }) => (
    <div data-testid="shared-history-list">
      <button type="button" onClick={onClose}>
        list-close
      </button>
      <button type="button" onClick={onNewChat}>
        new-chat
      </button>
      <button type="button" onClick={() => onSessionClick("session-1")}>
        open-session
      </button>
    </div>
  ),
}));

vi.mock("../../../../hooks/useIsMobile", () => ({
  useIsMobile: mockUseIsMobile,
}));

vi.mock("../../hooks/useCreateNewSession", () => ({
  useCreateNewSession: () => mockCreateSession,
}));

vi.mock("../../sessionApi", () => ({
  default: {
    getEffectiveSessionId: mockGetEffectiveSessionId,
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

describe("ChatSessionDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateSession.mockResolvedValue(undefined);
    mockGetEffectiveSessionId.mockImplementation((sessionId) => sessionId);
    mockUseIsMobile.mockReturnValue(true);
  });

  it("renders the shared history list only while open", () => {
    const { rerender } = render(
      <ChatSessionDrawer open={false} onClose={vi.fn()} />,
      { wrapper: MemoryRouter },
    );
    expect(screen.queryByTestId("shared-history-list")).toBeNull();

    rerender(<ChatSessionDrawer open onClose={vi.fn()} />);
    expect(screen.getByTestId("shared-history-list")).toBeVisible();
    expect(screen.getByTestId("drawer")).toHaveAttribute(
      "data-width",
      "calc(100vw - 56px)",
    );
  });

  it("forwards close actions from the drawer and shared list", () => {
    const onClose = vi.fn();
    render(<ChatSessionDrawer open onClose={onClose} />, {
      wrapper: MemoryRouter,
    });

    fireEvent.click(screen.getByText("drawer-close"));
    fireEvent.click(screen.getByText("list-close"));

    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("navigates to a selected session and closes", () => {
    const onClose = vi.fn();
    mockGetEffectiveSessionId.mockReturnValue("resolved-session");
    render(<ChatSessionDrawer open onClose={onClose} />, {
      wrapper: MemoryRouter,
    });

    fireEvent.click(screen.getByText("open-session"));

    expect(mockNavigate).toHaveBeenCalledWith("/chat/resolved-session");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("creates a session and closes after completion", async () => {
    const onClose = vi.fn();
    render(<ChatSessionDrawer open onClose={onClose} />, {
      wrapper: MemoryRouter,
    });

    fireEvent.click(screen.getByText("new-chat"));

    expect(mockCreateSession).toHaveBeenCalledOnce();
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it("closes even when session creation fails", async () => {
    const onClose = vi.fn();
    mockCreateSession.mockRejectedValue(new Error("create failed"));
    render(<ChatSessionDrawer open onClose={onClose} />, {
      wrapper: MemoryRouter,
    });

    fireEvent.click(screen.getByText("new-chat"));

    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });
});
