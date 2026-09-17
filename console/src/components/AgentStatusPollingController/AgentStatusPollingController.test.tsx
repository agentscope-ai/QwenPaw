import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentStatusPollingController } from ".";

const mocks = vi.hoisted(() => ({
  poll: vi.fn(),
  refreshAgents: vi.fn(),
  agents: [
    {
      id: "agent",
      name: "Agent",
      description: "",
      workspace_dir: "",
      enabled: true,
      pinned: false,
      startup_status: "starting" as const,
    },
  ],
}));

vi.mock("@/hooks/useAgentStatusPolling", () => ({
  useAgentStatusPolling: mocks.poll,
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: typeof mocks) => unknown) =>
    selector(mocks),
}));

describe("AgentStatusPollingController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("connects the shared store to the single polling hook", () => {
    render(<AgentStatusPollingController />);

    expect(mocks.poll).toHaveBeenCalledOnce();
    expect(mocks.poll).toHaveBeenCalledWith(mocks.agents, mocks.refreshAgents);
  });
});
