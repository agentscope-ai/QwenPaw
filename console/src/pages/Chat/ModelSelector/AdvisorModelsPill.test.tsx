import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/common_setup";
import { useAgentStore } from "@/stores/agentStore";
import { useAdvisorModeStore } from "@/stores/advisorModeStore";
import { useLoopStore } from "@/stores/loopStore";
import { providerApi } from "@/api/modules/provider";
import {
  AdvisorModelsPill,
  useIsAdvisorConversation,
} from "./AdvisorModelsPill";

vi.mock("@/api/modules/advisorMode", () => ({
  advisorModeApi: { get: vi.fn(), update: vi.fn() },
}));
vi.mock("@/api/modules/provider", () => ({
  providerApi: { listProviders: vi.fn() },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const ADVISOR = {
  id: "advisor",
  name: "Advisor",
  slash_command: "advisor",
  description: "",
  source: "plugin" as const,
};

beforeEach(() => {
  vi.clearAllMocks();
  useAgentStore.setState({ selectedAgent: "a1", agents: [] });
  useAdvisorModeStore.setState({
    advisorModeByAgent: {
      a1: {
        enabled: true,
        plan_enabled: true,
        followup_enabled: true,
        on_demand_enabled: true,
        advisor_model: { provider_id: "dash", model: "qwen3-max" },
        worker_model: { provider_id: "dash", model: "qwen-plus" },
        main_model: { provider_id: "dash", model: "qwen3-max" },
        subagent_model: { provider_id: "dash", model: "qwen-plus" },
        advisor_model_override: null,
        worker_model_override: null,
      },
    },
    advisorModeRevisionByAgent: {},
  });
  useLoopStore.getState().resetSessionMode();
  vi.mocked(providerApi.listProviders).mockResolvedValue([
    {
      id: "dash",
      name: "DashScope",
      api_key: "sk",
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
  ] as unknown as Awaited<ReturnType<typeof providerApi.listProviders>>);
});

describe("AdvisorModelsPill", () => {
  it("shows advisor \u2192 worker by display name and opens the panel", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AdvisorModelsPill />);
    const pill = screen.getByTestId("advisor-models-pill");
    await waitFor(() =>
      expect(pill).toHaveTextContent("Qwen3 Max \u2192 Qwen Plus"),
    );
    await user.click(pill);
    expect(await screen.findByTestId("advisor-setup")).toBeInTheDocument();
  });

  it("useIsAdvisorConversation follows the loop store", () => {
    const { result, rerender } = renderHook(() => useIsAdvisorConversation());
    expect(result.current).toBe(false);
    useLoopStore.getState().setAvailableModes([ADVISOR]);
    useLoopStore.getState().setSelectedMode("advisor");
    rerender();
    expect(result.current).toBe(true);
    useLoopStore.getState().resetSessionMode();
    useLoopStore.getState().setSessionMode(ADVISOR, "running");
    rerender();
    expect(result.current).toBe(true);
  });
});
