import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { agentsApi } from "@/api/modules/agents";
import { AgentMembersModal } from "./AgentMembersModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: {
    listMembers: vi.fn(),
    listShareableUsers: vi.fn(),
    grantMember: vi.fn(),
    revokeMember: vi.fn(),
    transferOwner: vi.fn(),
  },
}));

describe("AgentMembersModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentsApi.listMembers).mockResolvedValue([
      { user_id: "u1", username: "alice", role: "collaborator" },
    ]);
    vi.mocked(agentsApi.listShareableUsers).mockResolvedValue([
      { id: "u2", username: "bob", platform_role: "member" },
    ]);
  });

  it("loads members and allows the owner to grant a run-only role", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AgentMembersModal
        open
        agentId="a1"
        onClose={vi.fn()}
        onChanged={vi.fn()}
      />,
    );

    expect(await screen.findByText("alice")).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "agent.memberUser" }));
    await user.click(await screen.findByText("bob"));
    await user.click(screen.getByRole("button", { name: "agent.addMember" }));

    await waitFor(() => {
      expect(agentsApi.grantMember).toHaveBeenCalledWith("a1", "u2", "user");
    });
  });
});
