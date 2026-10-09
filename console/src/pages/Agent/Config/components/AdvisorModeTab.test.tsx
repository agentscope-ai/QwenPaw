import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "@/stores/agentStore";
import { useAdvisorModeStore } from "@/stores/advisorModeStore";
import { advisorModeApi } from "@/api/modules/advisorMode";
import { AdvisorModeTab } from "./AdvisorModeTab";

// Same as AgentLoopCard.render.test: the design package re-exports antd.
vi.mock("@agentscope-ai/design", async () =>
  vi.importActual<typeof import("antd")>("antd"),
);
vi.mock("@/api/modules/advisorMode", async () => ({
  ...(await vi.importActual<object>("@/api/modules/advisorMode")),
  advisorModeApi: { get: vi.fn(), update: vi.fn() },
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
  worker_model: { provider_id: "dash", model: "qwen-plus" },
  advisor_model_override: null,
  worker_model_override: null,
  main_model: { provider_id: "dash", model: "qwen3-max" },
  subagent_model: { provider_id: "dash", model: "qwen-plus" },
};

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
});

describe("AdvisorModeTab", () => {
  it("renders the built-in layout with one card per stage", async () => {
    renderWithProviders(<AdvisorModeTab />);
    await waitFor(() => expect(advisorModeApi.get).toHaveBeenCalled());
    // Tests run without translations: t() returns the key.
    expect(
      screen.getByText("agentConfig.loopMode.advisorDescription"),
    ).toBeInTheDocument();
    // Keys that carry a fallback render the fallback.
    expect(screen.getByText("Advisor pipeline")).toBeInTheDocument();
    for (const key of [
      "agentConfig.loopMode.advisorModelsTitle",
      "agentConfig.loopMode.advisorPlanTitle",
      "agentConfig.loopMode.advisorFollowupTitle",
      "agentConfig.loopMode.advisorOnDemandTitle",
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
    expect(
      screen.queryByText("agentConfig.loopMode.advisorModelsTitle"),
    ).toBeNull();
  });

  it("saves an intervention threshold when the field is left", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdvisorModeTab />);
    await screen.findByText("agentConfig.loopMode.advisorFollowupTitle");
    await user.click(
      screen.getByText("agentConfig.loopMode.advisorFollowupTitle"),
    );
    const field = await screen.findByRole("spinbutton", {
      name: "agentConfig.loopMode.advisorIntervention.consecutive_failures",
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
      name: "agentConfig.loopMode.advisorFollowupTitle",
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
});
