import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import AgentSelector from "./index";

const mocks = vi.hoisted(() => ({
  setSelectedAgent: vi.fn(),
  setAgents: vi.fn(),
  listAgents: vi.fn(),
  toggleAgentEnabled: vi.fn(),
  navigate: vi.fn(),
  storeState: {
    selectedAgent: "default",
    agents: [] as Array<Record<string, unknown>>,
  },
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: {
    listAgents: mocks.listAgents,
    toggleAgentEnabled: mocks.toggleAgentEnabled,
  },
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({
    ...mocks.storeState,
    setSelectedAgent: mocks.setSelectedAgent,
    setAgents: mocks.setAgents,
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
  },
  {
    id: "agent-1",
    name: "Agent One",
    enabled: true,
    description: "desc",
    workspace_dir: "",
    startup_status: "running",
  },
  {
    id: "agent-2",
    name: "Agent Two",
    enabled: false,
    description: "",
    workspace_dir: "",
    startup_status: "disabled",
  },
];

describe("AgentSelector", () => {
  beforeEach(() => {
    mocks.storeState.selectedAgent = "default";
    mocks.storeState.agents = agents;
    mocks.listAgents.mockResolvedValue({ agents });
    mocks.toggleAgentEnabled.mockResolvedValue({
      success: true,
      agent_id: "agent-2",
      enabled: true,
    });
  });

  afterEach(() => vi.clearAllMocks());

  it("calls listAgents on mount", async () => {
    renderWithProviders(<AgentSelector />);
    await waitFor(() => expect(mocks.listAgents).toHaveBeenCalledOnce());
  });

  it("does not render Select in collapsed mode", async () => {
    renderWithProviders(<AgentSelector collapsed />);
    await waitFor(() => expect(mocks.listAgents).toHaveBeenCalled());
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
