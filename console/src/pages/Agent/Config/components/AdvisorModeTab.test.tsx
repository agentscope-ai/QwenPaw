import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "@/stores/agentStore";
import { useAdvisorModeStore } from "@/stores/advisorModeStore";
import { advisorModeApi } from "@/api/modules/advisorMode";
import { providerApi } from "@/api/modules/provider";
import { AdvisorModeTab } from "./AdvisorModeTab";

// Same as AgentLoopCard.render.test: the design package re-exports antd.
vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);
vi.mock("@/api/modules/advisorMode", () => ({
  advisorModeApi: { get: vi.fn(), update: vi.fn() },
}));
vi.mock("@/api/modules/provider", () => ({
  providerApi: { listProviders: vi.fn() },
}));

const STATE = {
  enabled: true,
  plan_enabled: true,
  followup_enabled: false,
  on_demand_enabled: true,
  max_consults: 3,
  advisor_thinking: "inherit" as const,
  intervention: {
    consecutive_failures: 3,
    window_size: 10,
    window_failures: 4,
    cooldown_steps: 0,
    max_interventions: 3,
  },
  agent_id: "a1",
  advisor_model: { provider_id: "dash", model: "qwen3-max" },
  advisor_source: "main_model" as const,
  worker_model: { provider_id: "dash", model: "qwen-plus" },
  worker_source: "subagent_model" as const,
  advisor_model_override: null,
  worker_model_override: null,
  main_model: { provider_id: "dash", model: "qwen3-max" },
  subagent_model: { provider_id: "dash", model: "qwen-plus" },
};

const PROVIDERS = [
  {
    id: "dash",
    name: "DashScope",
    api_key: "sk-x",
    base_url: "https://x",
    require_api_key: true,
    is_custom: false,
    is_local: false,
    models: [
      { id: "qwen3-max", name: "Qwen3 Max" },
      { id: "qwen-plus", name: "Qwen Plus" },
    ],
    extra_models: [],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  useAgentStore.setState({ selectedAgent: "a1", agents: [] });
  useAdvisorModeStore.setState({
    advisorModeByAgent: {},
    advisorModeRevisionByAgent: {},
  });
  vi.mocked(advisorModeApi.get).mockResolvedValue(STATE);
  vi.mocked(advisorModeApi.update).mockImplementation(async (patch) => ({
    ...STATE,
    ...patch,
    intervention: { ...STATE.intervention, ...patch.intervention },
  }));
  vi.mocked(providerApi.listProviders).mockResolvedValue(
    PROVIDERS as unknown as Awaited<
      ReturnType<typeof providerApi.listProviders>
    >,
  );
});

describe("AdvisorModeTab", () => {
  it("renders the built-in layout with one card per stage", async () => {
    renderWithProviders(<AdvisorModeTab />);
    await waitFor(() => expect(advisorModeApi.get).toHaveBeenCalled());
    // Tests run without translations: t() returns the key.
    expect(
      screen.getByText("agentConfig.advisorModeTooltip"),
    ).toBeInTheDocument();
    // Keys that carry a fallback render the fallback.
    expect(screen.getByText("Advisor pipeline")).toBeInTheDocument();
    for (const key of [
      "agentConfig.advisorModeModelsTitle",
      "agentConfig.advisorModePlanTitle",
      "agentConfig.advisorModeFollowupTitle",
      "agentConfig.advisorModeOnDemandTitle",
    ]) {
      expect(screen.getByText(key)).toBeInTheDocument();
    }
    // One switch per capability plus the agent-level default.
    expect(await screen.findAllByRole("switch")).toHaveLength(4);
  });

  it("hides the pipeline while Advisor Mode is switched off", async () => {
    vi.mocked(advisorModeApi.get).mockResolvedValue({
      ...STATE,
      enabled: false,
    });
    renderWithProviders(<AdvisorModeTab />);
    await waitFor(() => expect(advisorModeApi.get).toHaveBeenCalled());
    expect(await screen.findAllByRole("switch")).toHaveLength(1);
    expect(screen.queryByText("Advisor pipeline")).toBeNull();
    expect(screen.queryByText("agentConfig.advisorModeModelsTitle")).toBeNull();
  });

  it("saves an intervention threshold when the field is left", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdvisorModeTab />);
    await screen.findByText("agentConfig.advisorModeFollowupTitle");
    await user.click(screen.getByText("agentConfig.advisorModeFollowupTitle"));
    const field = await screen.findByRole("spinbutton", {
      name: "agentConfig.advisorIntervention.consecutive_failures",
    });
    await user.clear(field);
    await user.type(field, "2");
    await user.tab();
    await waitFor(() =>
      expect(advisorModeApi.update).toHaveBeenCalledWith({
        intervention: { consecutive_failures: 2 },
      }),
    );
    expect(advisorModeApi.update).toHaveBeenCalledTimes(1);
  });

  it("switches save straight to the backend and update the store", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdvisorModeTab />);
    const followup = await screen.findByRole("switch", {
      name: "agentConfig.advisorModeFollowup",
    });
    expect(followup).not.toBeChecked();
    await user.click(followup);
    await waitFor(() =>
      expect(advisorModeApi.update).toHaveBeenCalledWith({
        followup_enabled: true,
      }),
    );
    await waitFor(() =>
      expect(
        useAdvisorModeStore.getState().advisorModeByAgent["a1"]
          ?.followup_enabled,
      ).toBe(true),
    );
  });

  it("offers the default slot plus every model, and saves an override", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdvisorModeTab />);
    await screen.findByText("agentConfig.advisorModeModelsTitle");
    await user.click(screen.getByText("agentConfig.advisorModeModelsTitle"));
    const teacher = await screen.findByTestId("advisor-advisor-model");
    // The default entry stands for the main model.
    expect(
      within(teacher).getByText("agentConfig.advisorModeMainModel"),
    ).toBeInTheDocument();
    await user.click(within(teacher).getByRole("combobox"));
    await user.click(await screen.findByText("DashScope / Qwen Plus"));
    await waitFor(() =>
      expect(advisorModeApi.update).toHaveBeenCalledWith({
        advisor_model: { provider_id: "dash", model: "qwen-plus" },
      }),
    );
  });

  it("picking the default slot clears the override with null", async () => {
    const user = userEvent.setup();
    vi.mocked(advisorModeApi.get).mockResolvedValue({
      ...STATE,
      worker_model_override: { provider_id: "dash", model: "qwen-plus" },
      worker_source: "override",
    });
    renderWithProviders(<AdvisorModeTab />);
    await screen.findByText("agentConfig.advisorModeModelsTitle");
    await user.click(screen.getByText("agentConfig.advisorModeModelsTitle"));
    const student = await screen.findByTestId("advisor-worker-model");
    await user.click(within(student).getByRole("combobox"));
    const entries = await screen.findAllByText(
      "agentConfig.advisorModeSubagentModel",
    );
    await user.click(entries[entries.length - 1]); // the dropdown option
    await waitFor(() =>
      expect(advisorModeApi.update).toHaveBeenCalledWith({
        worker_model: null,
      }),
    );
  });
});
