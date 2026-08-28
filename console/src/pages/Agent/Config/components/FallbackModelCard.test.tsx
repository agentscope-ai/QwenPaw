import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FallbackModelCardHandle } from "./FallbackModelCard";
import { FallbackModelCard } from "./FallbackModelCard";

const mocks = vi.hoisted(() => ({
  getAgent: vi.fn(),
  updateModelSettings: vi.fn(),
  listProviders: vi.fn(),
  getActiveModels: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

const translate = vi.hoisted(
  () => (key: string, values?: { count?: number; model?: string }) => {
    if (values?.model) return `${key}:${values.model}`;
    if (values?.count !== undefined) return `${key}:${values.count}`;
    return key;
  },
);

vi.mock("@agentscope-ai/design", async () => {
  const React = await import("react");
  const Card = ({ children, ...props }: Record<string, unknown>) =>
    React.createElement("div", props, children as React.ReactNode);
  const Select = ({
    options = [],
    value,
    onChange,
    ...props
  }: Record<string, unknown>) =>
    React.createElement(
      "select",
      {
        ...props,
        value,
        onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
          (onChange as ((next: string) => void) | undefined)?.(
            event.target.value,
          ),
      },
      (options as Array<{ label: string; value: string }>).map((option) =>
        React.createElement(
          "option",
          { key: option.value, value: option.value },
          option.label,
        ),
      ),
    );
  const Switch = ({ checked, onChange, ...props }: Record<string, unknown>) =>
    React.createElement("input", {
      ...props,
      type: "checkbox",
      checked,
      onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
        (onChange as ((next: boolean) => void) | undefined)?.(
          event.target.checked,
        ),
    });
  return { Card, Select, Switch };
});

vi.mock("@/api/modules/agents", () => ({
  agentsApi: {
    getAgent: mocks.getAgent,
    updateModelSettings: mocks.updateModelSettings,
  },
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: mocks.listProviders,
    getActiveModels: mocks.getActiveModels,
  },
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mocks }),
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "default" }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: translate,
  }),
}));

const provider = {
  id: "openai",
  name: "OpenAI",
  api_key_prefix: "sk-",
  chat_model: "primary",
  models: [
    {
      id: "primary",
      name: "GPT-4",
      is_free: false,
    },
    {
      id: "backup",
      name: "GPT-4 Mini",
      is_free: false,
    },
  ],
  extra_models: [],
  api_key: "sk-test",
  base_url: "https://api.openai.com/v1",
  is_custom: false,
  is_local: false,
  require_api_key: true,
  support_model_discovery: false,
  support_connection_check: true,
  freeze_url: false,
  generate_kwargs: {},
};

const secondProvider = {
  ...provider,
  id: "anthropic",
  name: "Anthropic",
  models: [
    {
      id: "claude",
      name: "Claude",
      is_free: false,
    },
  ],
};

function renderCard() {
  const ref = createRef<FallbackModelCardHandle>();
  render(<FallbackModelCard ref={ref} />);
  return ref;
}

describe("FallbackModelCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getAgent.mockResolvedValue({
      id: "default",
      name: "Default",
      active_model: { provider_id: "openai", model: "primary" },
      fallback_models: [{ provider_id: "openai", model: "backup" }],
      fallback_policy: { enabled: true, target_scope: "configured" },
    });
    mocks.listProviders.mockResolvedValue([provider, secondProvider]);
    mocks.getActiveModels.mockResolvedValue({
      active_llm: { provider_id: "openai", model: "primary" },
    });
    mocks.updateModelSettings.mockImplementation(
      async (_agentId, settings) => ({
        id: "default",
        name: "Default",
        active_model: { provider_id: "openai", model: "primary" },
        ...settings,
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the saved fallback chain and adds a model", async () => {
    renderCard();

    expect(await screen.findByText("OpenAI / GPT-4 Mini")).toBeInTheDocument();
    const select = screen.getByLabelText("agentConfig.fallbackChooseModel");
    fireEvent.change(select, { target: { value: "anthropic:claude" } });
    fireEvent.click(screen.getByTitle("agentConfig.fallbackAddModel"));

    expect(screen.getByText("Anthropic / Claude")).toBeInTheDocument();
  });

  it("saves the fallback policy and ordered model slots", async () => {
    const ref = renderCard();
    await screen.findByText("OpenAI / GPT-4 Mini");

    fireEvent.change(screen.getByLabelText("agentConfig.fallbackChooseModel"), {
      target: { value: "anthropic:claude" },
    });
    fireEvent.click(screen.getByTitle("agentConfig.fallbackAddModel"));
    await screen.findByTitle(
      "agentConfig.fallbackRemoveModel:Anthropic / Claude",
    );

    await act(async () => {
      await ref.current?.save();
    });

    await waitFor(() =>
      expect(mocks.updateModelSettings).toHaveBeenCalledWith("default", {
        fallback_models: [
          { provider_id: "openai", model: "backup" },
          { provider_id: "anthropic", model: "claude" },
        ],
        fallback_policy: { enabled: true, target_scope: "configured" },
      }),
    );
    expect(mocks.success).toHaveBeenCalledWith(
      "agentConfig.fallbackSaveSuccess",
    );
  });

  it("removes a model and supports disabling fallback", async () => {
    renderCard();
    await screen.findByText("OpenAI / GPT-4 Mini");

    fireEvent.click(
      screen.getByTitle("agentConfig.fallbackRemoveModel:OpenAI / GPT-4 Mini"),
    );
    expect(
      screen.queryByTitle(
        "agentConfig.fallbackRemoveModel:OpenAI / GPT-4 Mini",
      ),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
});
