// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { sharedAppsApi } from "@/api/modules/sharedApps";
import { useAgentStore } from "@/stores/agentStore";
import { SharedApps } from "./SharedApps";

const navigate = vi.fn();
vi.mock("react-router-dom", async (original) => ({
  ...(await original<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));
vi.mock("@/api/modules/sharedApps", () => ({
  sharedAppsApi: { catalog: vi.fn(), start: vi.fn() },
}));

describe("SharedApps", () => {
  beforeEach(() => {
    navigate.mockReset();
    useAgentStore.setState({ selectedAgent: "", agents: [] });
    vi.mocked(sharedAppsApi.catalog).mockResolvedValue({ items: [{
      id: "publication-1", shared_app_id: "app-1", version: "r2",
      review_status: "approved", immutable_manifest: {
        display: { name: "共享演示" },
        model: { provider_id: "provider", model: "model" },
      },
    }] });
    vi.mocked(sharedAppsApi.start).mockResolvedValue({
      agent_id: "agent-1", conversation_id: "conversation-1",
      publication_id: "publication-1", version: "r2",
      locked_model: { provider_id: "provider", model: "model" },
    });
  });

  it("starts a private conversation and selects its source Agent", async () => {
    render(<MemoryRouter><SharedApps /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "开始使用" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/chat/conversation-1"));
    expect(sharedAppsApi.start).toHaveBeenCalledWith("app-1");
    expect(useAgentStore.getState().selectedAgent).toBe("agent-1");
  });
});
