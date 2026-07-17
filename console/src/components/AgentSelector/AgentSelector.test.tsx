import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import AgentSelector from "./index";

const mocks = vi.hoisted(() => ({
  setSelectedAgent: vi.fn(),
  setAgents: vi.fn(),
  refreshAgents: vi.fn(),
  toggleAgentEnabled: vi.fn(),
  setAgentPinned: vi.fn(),
  navigate: vi.fn(),
  storeState: {
    selectedAgent: "default",
    agents: [] as Array<Record<string, unknown>>,
  },
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: {
    toggleAgentEnabled: mocks.toggleAgentEnabled,
    setAgentPinned: mocks.setAgentPinned,
  },
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({
    ...mocks.storeState,
    setSelectedAgent: mocks.setSelectedAgent,
    setAgents: mocks.setAgents,
    refreshAgents: mocks.refreshAgents,
  })),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mocks.navigate };
});

const agents = [
  {
    id: "default",
    name: "Default",
    enabled: true,
    description: "",
    workspace_dir: "",
    startup_status: "running",
    pinned: true,
  },
  {
    id: "agent-1",
    name: "Agent One",
    enabled: true,
    description: "desc",
    workspace_dir: "",
    startup_status: "running",
    pinned: false,
  },
  {
    id: "agent-2",
    name: "Agent Two",
    enabled: false,
    description: "",
    workspace_dir: "",
    startup_status: "disabled",
    pinned: false,
  },
];

describe("AgentSelector", () => {
  beforeEach(() => {
    mocks.storeState.selectedAgent = "default";
    mocks.storeState.agents = agents;
    mocks.refreshAgents.mockResolvedValue(undefined);
    mocks.toggleAgentEnabled.mockResolvedValue({
      success: true,
      agent_id: "agent-2",
      enabled: true,
    });
    mocks.setAgentPinned.mockResolvedValue({
      success: true,
      agent_id: "agent-1",
      pinned: true,
    });
  });

  afterEach(() => vi.clearAllMocks());

  it("refreshes the shared agent store on mount", async () => {
    renderWithProviders(<AgentSelector />);
    await waitFor(() => expect(mocks.refreshAgents).toHaveBeenCalledOnce());
  });

  it("does not render Select in collapsed mode", async () => {
    renderWithProviders(<AgentSelector collapsed />);
    await waitFor(() => expect(mocks.refreshAgents).toHaveBeenCalled());
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("shows disabled agents only after expanding the footer", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AgentSelector />);

    await user.click(screen.getByRole("combobox"));
    expect(screen.queryByText("Agent Two")).not.toBeInTheDocument();

    const disabledHeader = screen.getByRole("button", {
      name: "agent.disabledAgents",
    });
    expect(disabledHeader).toHaveAttribute("aria-expanded", "false");
    await user.click(disabledHeader);

    expect(disabledHeader).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Agent Two")).toBeInTheDocument();
  });

  it("keeps a pinned disabled agent visible and lets it be enabled", async () => {
    const pinnedDisabledAgent = {
      id: "agent-3",
      name: "Pinned Disabled",
      enabled: false,
      pinned: true,
      description: "",
      workspace_dir: "",
      startup_status: "disabled",
    };
    const nextAgents = [...agents, pinnedDisabledAgent];
    mocks.storeState.agents = nextAgents;
    const user = userEvent.setup();
    renderWithProviders(<AgentSelector />);

    await user.click(screen.getByRole("combobox"));
    expect(screen.getByText("Pinned Disabled")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "agent.enableAgent" }));

    expect(mocks.toggleAgentEnabled).toHaveBeenCalledWith("agent-3", true);
  });

  it("optimistically marks an enabled agent as starting", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AgentSelector />);
    await user.click(screen.getByRole("combobox"));
    await user.click(
      screen.getByRole("button", { name: "agent.disabledAgents" }),
    );
    await user.click(screen.getByRole("button", { name: "agent.enableAgent" }));

    expect(mocks.toggleAgentEnabled).toHaveBeenCalledWith("agent-2", true);
    expect(mocks.setAgents).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          id: "agent-2",
          enabled: true,
          startup_status: "starting",
        }),
      ]),
    );
  });

  it("switches to default after disabling the selected agent", async () => {
    mocks.storeState.selectedAgent = "agent-1";
    const user = userEvent.setup();
    renderWithProviders(<AgentSelector />);
    await user.click(screen.getByRole("combobox"));
    await user.click(
      screen.getByRole("button", { name: "agent.disableAgent" }),
    );

    await waitFor(() => {
      expect(mocks.toggleAgentEnabled).toHaveBeenCalledWith("agent-1", false);
    });
    expect(mocks.setSelectedAgent).toHaveBeenCalledWith("default");
  });
});
