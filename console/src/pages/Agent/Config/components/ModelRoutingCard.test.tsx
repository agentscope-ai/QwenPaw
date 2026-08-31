import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { renderWithProviders } from "@/test/common_setup";
import type { AgentModelRoutingDraft, ProviderInfo } from "@/api/types";

const translation = vi.hoisted(() => ({
  t: (key: string) => key,
}));

vi.mock("@agentscope-ai/design", async () => {
  const Select = ({
    options = [],
    value,
    onChange,
    showSearch: _showSearch,
    optionFilterProp: _optionFilterProp,
    ...props
  }: {
    options?: { value: string; label: string }[];
    value?: string;
    onChange?: (value: string) => void;
    [key: string]: unknown;
  }) => {
    void _showSearch;
    void _optionFilterProp;
    return (
      <select
        {...props}
        value={value ?? ""}
        onChange={(event) => onChange?.(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  };
  const Card = ({ children }: { children: ReactNode }) => <div>{children}</div>;
  const Button = ({ children }: { children: ReactNode }) => (
    <button type="button">{children}</button>
  );
  return { Button, Card, Select };
});

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: vi.fn(),
  },
}));

vi.mock("../../../Chat/ModelSelector/AgentModelSettings", () => ({
  AgentModelSettings: () => null,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => translation,
}));

import { providerApi } from "@/api/modules/provider";
import { ModelRoutingCard } from "./ModelRoutingCard";

const provider: ProviderInfo = {
  id: "openai",
  name: "OpenAI",
  api_key_prefix: "sk-",
  chat_model: "OpenAIChatModel",
  models: [
    {
      id: "visible-model",
      name: "Visible Model",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      max_input_length: 32768,
      generate_kwargs: {},
      relay_reasoning: true,
      thinking_enabled: null,
      thinking_budget: null,
      reasoning_effort: null,
    },
    {
      id: "hidden-model",
      name: "Hidden Model",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      max_input_length: 32768,
      generate_kwargs: {},
      relay_reasoning: true,
      thinking_enabled: null,
      thinking_budget: null,
      reasoning_effort: null,
    },
  ],
  extra_models: [],
  hidden_model_ids: ["hidden-model"],
  is_custom: false,
  is_local: false,
  support_model_discovery: false,
  support_connection_check: false,
  freeze_url: false,
  require_api_key: true,
  api_key: "sk-test",
  base_url: "",
  generate_kwargs: {},
};

const modelRouting: AgentModelRoutingDraft = {
  active_model: { provider_id: "openai", model: "visible-model" },
  fallback_models: [],
  fallback_policy: { enabled: true, target_scope: "configured" },
  subagent_model: null,
};

describe("ModelRoutingCard", () => {
  it("does not show hidden models in the primary model selector", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([provider]);

    renderWithProviders(
      <ModelRoutingCard
        modelRouting={modelRouting}
        onModelRoutingChange={vi.fn()}
        draftResetToken={0}
      />,
    );

    await waitFor(() => expect(providerApi.listProviders).toHaveBeenCalled());
    const modelSelect = await screen.findByLabelText("models.model");
    const optionLabels = Array.from(modelSelect.querySelectorAll("option")).map(
      (option) => option.textContent,
    );
    expect(optionLabels).toContain("Visible Model (visible-model)");
    expect(optionLabels).not.toContain("Hidden Model (hidden-model)");
  });
});
