import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "@/stores/agentStore";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listAgents: vi.fn(),
  updateModelSettings: vi.fn(),
  listProviders: vi.fn(),
  getActiveModels: vi.fn(),
  setActiveLlm: vi.fn(),
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: {
    listAgents: apiMocks.listAgents,
    updateModelSettings: apiMocks.updateModelSettings,
  },
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: apiMocks.listProviders,
    getActiveModels: apiMocks.getActiveModels,
    setActiveLlm: apiMocks.setActiveLlm,
  },
}));

vi.mock("@/pages/Chat/ModelSelector/ModelChoice", () => ({
  ModelChoice: ({ label }: { label: string }) => (
    <button type="button">{label}</button>
  ),
}));

vi.mock("@/pages/Chat/ModelSelector/AgentModelSettings", () => ({
  AgentModelSettings: ({
    agentId,
    autoSave,
  }: {
    agentId: string;
    autoSave?: boolean;
  }) => (
    <div data-testid="agent-model-settings" data-auto-save={autoSave}>
      {agentId}
    </div>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { AgentModelCard } from "./AgentModelCard";

describe("AgentModelCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAgentStore.setState({ selectedAgent: "default", agents: [] });
    apiMocks.listAgents.mockResolvedValue({
      agents: [
        {
          id: "default",
          name: "Default",
          backend: "qwenpaw",
          active_model: null,
        },
      ],
    });
    apiMocks.listProviders.mockResolvedValue([]);
    apiMocks.getActiveModels.mockResolvedValue({
      active_llm: { provider_id: "openai", model: "gpt-4" },
    });
  });

  it("renders the selected agent model settings in the work environment", async () => {
    renderWithProviders(<AgentModelCard />);

    expect(
      await screen.findByRole("region", { name: "models.agentDefaults" }),
    ).toBeInTheDocument();
    expect(await screen.findByTestId("agent-model-settings")).toHaveTextContent(
      "default",
    );
    expect(await screen.findByTestId("agent-model-settings")).toHaveAttribute(
      "data-auto-save",
      "true",
    );
    expect(
      screen.getAllByRole("button", {
        name: "thinkingControl.modelSource.global",
      }),
    ).toHaveLength(2);
  });

  it("does not show QwenPaw model routing for another backend", async () => {
    apiMocks.listAgents.mockResolvedValue({
      agents: [{ id: "default", name: "Codex", backend: "codex" }],
    });

    renderWithProviders(<AgentModelCard />);

    await waitFor(() =>
      expect(
        screen.queryByRole("region", { name: "models.agentDefaults" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("offers a retry without leaving a permanent loading state", async () => {
    const user = userEvent.setup();
    apiMocks.listAgents
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({
        agents: [
          {
            id: "default",
            name: "Default",
            backend: "qwenpaw",
            active_model: null,
          },
        ],
      });

    renderWithProviders(<AgentModelCard />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "models.agentRuntimeLoadFailed",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "common.retry" }));

    expect(await screen.findByTestId("agent-model-settings")).toHaveTextContent(
      "default",
    );
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("ignores a stale load failure after the selected agent changes", async () => {
    let rejectFirstRequest: (reason?: unknown) => void = () => undefined;
    apiMocks.listProviders
      .mockReturnValueOnce(
        new Promise((_, reject) => {
          rejectFirstRequest = reject;
        }),
      )
      .mockResolvedValue([]);
    apiMocks.listAgents.mockResolvedValue({
      agents: [
        { id: "default", name: "Default", backend: "qwenpaw" },
        { id: "other", name: "Other", backend: "qwenpaw" },
      ],
    });

    renderWithProviders(<AgentModelCard />);
    act(() => useAgentStore.setState({ selectedAgent: "other" }));

    expect(await screen.findByTestId("agent-model-settings")).toHaveTextContent(
      "other",
    );
    await act(async () => rejectFirstRequest(new Error("stale")));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
