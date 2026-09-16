import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listConversationMembers: vi.fn(),
  listConversationShareCandidates: vi.fn(),
  addConversationViewer: vi.fn(),
  removeConversationViewer: vi.fn(),
}));

vi.mock("../../../api/modules/chat", () => ({ chatApi: apiMocks }));
vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: vi.fn(), error: vi.fn() },
  }),
}));

import ConversationShareDialog from "./ConversationShareDialog";

describe("ConversationShareDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listConversationMembers.mockResolvedValue([
      {
        conversation_id: "chat-1",
        user_id: "member-1",
        username: "viewer-user",
        role: "viewer",
        granted_by: "owner-1",
        created_at: "2026-08-29T00:00:00Z",
      },
    ]);
    apiMocks.listConversationShareCandidates.mockResolvedValue([
      {
        user_id: "candidate-1",
        username: "eligible-user",
        platform_role: "member",
      },
    ]);
    apiMocks.addConversationViewer.mockResolvedValue({});
    apiMocks.removeConversationViewer.mockResolvedValue({
      success: true,
      removed: true,
    });
  });

  it("lists current viewers and only Agent-eligible candidates", async () => {
    render(<ConversationShareDialog open chatId="chat-1" onClose={vi.fn()} />);

    expect(await screen.findByText("viewer-user")).toBeInTheDocument();
    expect(apiMocks.listConversationMembers).toHaveBeenCalledWith("chat-1");
    expect(apiMocks.listConversationShareCandidates).toHaveBeenCalledWith(
      "chat-1",
    );
  });

  it("revokes a viewer through the owner-only API", async () => {
    render(<ConversationShareDialog open chatId="chat-1" onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "移除" }));

    await waitFor(() =>
      expect(apiMocks.removeConversationViewer).toHaveBeenCalledWith(
        "chat-1",
        "member-1",
      ),
    );
  });
});
