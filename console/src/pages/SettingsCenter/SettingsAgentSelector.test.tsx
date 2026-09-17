import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";

const mocks = vi.hoisted(() => ({
  refreshAgents: vi.fn(),
  setSelectedAgent: vi.fn(),
  state: {
    selectedAgent: "default",
    agents: [
      {
        id: "default",
        name: "Default",
        description: "",
        workspace_dir: "",
        enabled: true,
        startup_status: "running" as const,
        backend: "qwenpaw",
      },
      {
        id: "agent-1",
        name: "Agent One",
        description: "",
        workspace_dir: "",
        enabled: true,
        startup_status: "running" as const,
        backend: "codex",
      },
    ],
  },
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: () => ({
    ...mocks.state,
    refreshAgents: mocks.refreshAgents,
    setSelectedAgent: mocks.setSelectedAgent,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "agent.currentWorkspace": "Current Agent",
        "agent.selectAgent": "Select Agent",
      })[key] ?? key,
  }),
}));

import SettingsAgentSelector from "./SettingsAgentSelector";

describe("SettingsAgentSelector", () => {
  beforeEach(() => {
    mocks.setSelectedAgent.mockReset();
    mocks.refreshAgents.mockReset();
  });

  it("shows and switches the shared current agent", async () => {
    renderWithProviders(<SettingsAgentSelector />);

    expect(screen.getByText("Default")).toBeVisible();
    expect(screen.queryByText("Current Agent")).not.toBeInTheDocument();
    expect(screen.queryByText("qwenpaw")).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("combobox", { name: "Select Agent" }),
    );
    expect(screen.getByText("qwenpaw")).toBeInTheDocument();
    expect(screen.getByText("codex")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Agent One"));

    expect(mocks.setSelectedAgent).toHaveBeenCalledWith("agent-1");
  });
});
