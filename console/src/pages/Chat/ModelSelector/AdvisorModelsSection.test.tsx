import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "@/stores/agentStore";
import { useAdvisorModeStore } from "@/stores/advisorModeStore";
import { advisorModeApi } from "@/api/modules/advisorMode";
import { AdvisorModelsSection } from "./AdvisorModelsSection";

vi.mock("@/api/modules/advisorMode", () => ({
  advisorModeApi: { update: vi.fn() },
}));

const STATE = {
  enabled: true,
  plan_enabled: true,
  followup_enabled: true,
  on_demand_enabled: true,
  max_consults: 32,
  intervention: {
    consecutive_failures: 3,
    window_size: 10,
    window_failures: 4,
    cooldown_steps: 0,
    max_interventions: 3,
  },
  advisor_thinking: "inherit" as const,
  agent_id: "a1",
  advisor_model: { provider_id: "dash", model: "qwen3-max" },
  advisor_source: "main_model" as const,
  worker_model: { provider_id: "dash", model: "qwen-plus" },
  worker_source: "override" as const,
  advisor_model_override: null,
  worker_model_override: { provider_id: "dash", model: "qwen-plus" },
  main_model: { provider_id: "dash", model: "qwen3-max" },
  subagent_model: null,
};

const PROVIDERS = [
  {
    id: "dash",
    name: "DashScope",
    models: [
      { id: "qwen3-max", name: "Qwen3 Max" },
      { id: "qwen-plus", name: "Qwen Plus" },
    ],
  },
] as unknown as Parameters<typeof AdvisorModelsSection>[0]["providers"];

beforeEach(() => {
  vi.clearAllMocks();
  useAgentStore.setState({ selectedAgent: "a1", agents: [] });
  useAdvisorModeStore.setState({
    advisorModeByAgent: {},
    advisorModeRevisionByAgent: {},
  });
});

describe("AdvisorModelsSection", () => {
  it("renders nothing until the agent's Advisor Mode state is known or when it is off", () => {
    const { unmount } = renderWithProviders(
      <AdvisorModelsSection providers={PROVIDERS} />,
    );
    expect(screen.queryByTestId("advisor-models")).toBeNull();
    unmount();
    useAdvisorModeStore.getState().setAdvisorMode("a1", {
      ...STATE,
      enabled: false,
    });
    renderWithProviders(<AdvisorModelsSection providers={PROVIDERS} />);
    expect(screen.queryByTestId("advisor-models")).toBeNull();
  });

  it("shows the models in effect and saves a new worker model", async () => {
    const user = userEvent.setup();
    useAdvisorModeStore.getState().setAdvisorMode("a1", STATE);
    vi.mocked(advisorModeApi.update).mockResolvedValue({
      ...STATE,
      worker_model: { provider_id: "dash", model: "qwen3-max" },
      worker_model_override: { provider_id: "dash", model: "qwen3-max" },
    });
    renderWithProviders(<AdvisorModelsSection providers={PROVIDERS} />);
    const section = screen.getByTestId("advisor-models");
    // Summary line: keys render as-is without translations.
    expect(
      within(section).getByText("agentConfig.advisorModeModels"),
    ).toBeInTheDocument();
    const worker = within(section).getByRole("combobox", {
      name: "agentConfig.advisorModeWorkerModel",
    });
    await user.click(worker);
    await user.click(await screen.findByText("DashScope / Qwen3 Max"));
    await waitFor(() =>
      expect(advisorModeApi.update).toHaveBeenCalledWith({
        worker_model: { provider_id: "dash", model: "qwen3-max" },
      }),
    );
    await waitFor(() =>
      expect(
        useAdvisorModeStore.getState().advisorModeByAgent["a1"]?.worker_model
          ?.model,
      ).toBe("qwen3-max"),
    );
  });
});
