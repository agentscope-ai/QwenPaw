import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "@/stores/agentStore";
import { useAdvisorModeStore } from "@/stores/advisorModeStore";
import { advisorModeApi } from "@/api/modules/advisorMode";
import { providerApi } from "@/api/modules/provider";
import { AdvisorSetupPopover } from "./AdvisorSetupPopover";

vi.mock("@/api/modules/advisorMode", () => ({
  advisorModeApi: { get: vi.fn(), update: vi.fn() },
}));
vi.mock("@/api/modules/provider", () => ({
  providerApi: { listProviders: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, string>) =>
      opts?.model ? `${key}:${opts.model}` : key,
    i18n: { language: "en" },
  }),
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
  worker_model: null,
  worker_source: "main_model" as const,
  advisor_model_override: null,
  worker_model_override: null,
  main_model: { provider_id: "dash", model: "qwen3-max" },
  subagent_model: null,
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
    advisorModeByAgent: { a1: STATE },
    advisorModeRevisionByAgent: {},
  });
  vi.mocked(providerApi.listProviders).mockResolvedValue(
    PROVIDERS as unknown as Awaited<
      ReturnType<typeof providerApi.listProviders>
    >,
  );
  vi.mocked(advisorModeApi.update).mockImplementation(async (patch) => ({
    ...STATE,
    ...patch,
    intervention: STATE.intervention,
  }));
});

describe("AdvisorSetupPopover", () => {
  it("shows the defaults for both roles and the models in effect", async () => {
    renderWithProviders(<AdvisorSetupPopover open onOpenChange={() => {}} />);
    const setup = await screen.findByTestId("advisor-setup");
    expect(setup).toHaveTextContent(
      "loop.advisorSetup.mainModelDefault:dash / qwen3-max",
    );
    expect(setup).toHaveTextContent("loop.advisorSetup.noSubagent");
    expect(setup).toHaveTextContent("loop.advisorSetup.summary");
    await waitFor(() => expect(providerApi.listProviders).toHaveBeenCalled());
  });

  it("saves a worker model for the agent", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdvisorSetupPopover open onOpenChange={() => {}} />);
    await waitFor(() => expect(providerApi.listProviders).toHaveBeenCalled());
    const worker = await screen.findByRole("combobox", {
      name: "loop.advisorSetup.workerModel",
    });
    await user.click(worker);
    await user.click(await screen.findByText("DashScope / Qwen Plus"));
    await waitFor(() =>
      expect(advisorModeApi.update).toHaveBeenCalledWith({
        worker_model: { provider_id: "dash", model: "qwen-plus" },
      }),
    );
  });

  it("does not load providers while closed", () => {
    renderWithProviders(
      <AdvisorSetupPopover open={false} onOpenChange={() => {}} />,
    );
    expect(
      screen.getByRole("button", { name: "loop.advisorSetup.openAria" }),
    ).toBeInTheDocument();
    expect(providerApi.listProviders).not.toHaveBeenCalled();
  });
});
