import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import type { ProviderInfo } from "@/api/types";
import { RemoteProviderCard } from "./RemoteProviderCard";
import { ProviderGroupCard } from "./ProviderGroupCard";

const { configureProviderMock } = vi.hoisted(() => ({
  configureProviderMock: vi.fn(),
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    configureProvider: configureProviderMock,
  },
}));

beforeEach(() => {
  configureProviderMock.mockReset();
  configureProviderMock.mockResolvedValue({});
});

it.each([false, true])(
  "edits API keys inline and masks configured keys consistently (group=%s)",
  async (grouped) => {
    const provider: ProviderInfo = {
      api_key_prefix: "",
      api_key: "",
      chat_model: "OpenAIChatModel",
      is_custom: false,
      is_local: false,
      support_model_discovery: true,
      support_connection_check: true,
      freeze_url: false,
      generate_kwargs: {},
      id: "kilo",
      name: "Kilo",
      models: [],
      extra_models: [],
      require_api_key: grouped,
      base_url: "https://example.test",
    };
    const onOpenConfig = vi.fn();
    const onSaved = vi.fn();
    const props = { onOpenConfig, onSaved, onOpenModels: vi.fn() };
    const card = (value: ProviderInfo) =>
      grouped ? (
        <ProviderGroupCard
          {...props}
          group={{ groupKey: "test", groupName: "Test", providers: [value] }}
        />
      ) : (
        <RemoteProviderCard {...props} provider={value} />
      );
    const view = renderWithProviders(card(provider));
    fireEvent.click(screen.getByRole("button", { name: "models.add" }));
    expect(onOpenConfig).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("models.apiKey"), {
      target: { value: "test-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "models.saveApiKey" }));
    await waitFor(() => {
      expect(configureProviderMock).toHaveBeenCalledWith("kilo", {
        api_key: "test-key",
      });
    });
    expect(onSaved).toHaveBeenCalledOnce();

    const configured = { ...provider, api_key: "sk-ant-******" };
    view.rerender(card(configured));
    expect(screen.getByText("••••••••")).toBeInTheDocument();
    expect(screen.queryByText(configured.api_key)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "models.changeApiKey" }),
    );
    expect(screen.getByLabelText("models.apiKey")).toBeInTheDocument();
    expect(onOpenConfig).not.toHaveBeenCalled();
  },
);

it("localizes known provider variant labels", () => {
  const provider: ProviderInfo = {
    api_key_prefix: "",
    api_key: "secret",
    chat_model: "OpenAIChatModel",
    is_custom: false,
    is_local: false,
    support_model_discovery: true,
    support_connection_check: true,
    freeze_url: false,
    generate_kwargs: {},
    id: "coding-cn",
    name: "Coding CN",
    provider_variant: "coding_plan_cn",
    models: [],
    extra_models: [],
    require_api_key: true,
    base_url: "https://example.test",
  };

  renderWithProviders(
    <ProviderGroupCard
      group={{
        groupKey: "coding",
        groupName: "Coding",
        providers: [provider],
      }}
      onOpenConfig={vi.fn()}
      onOpenModels={vi.fn()}
      onSaved={vi.fn()}
    />,
  );

  expect(
    screen.getByText("models.providerVariants.coding_plan_cn"),
  ).toBeInTheDocument();
});

it("clears an unsaved API key when switching provider variants", () => {
  const baseProvider: ProviderInfo = {
    api_key_prefix: "",
    api_key: "",
    chat_model: "OpenAIChatModel",
    is_custom: false,
    is_local: false,
    support_model_discovery: true,
    support_connection_check: true,
    freeze_url: false,
    generate_kwargs: {},
    id: "first",
    name: "First",
    models: [],
    extra_models: [],
    require_api_key: true,
    base_url: "https://example.test",
  };

  renderWithProviders(
    <ProviderGroupCard
      group={{
        groupKey: "switchable",
        groupName: "Switchable",
        providers: [
          baseProvider,
          { ...baseProvider, id: "second", name: "Second" },
        ],
      }}
      onOpenConfig={vi.fn()}
      onOpenModels={vi.fn()}
      onSaved={vi.fn()}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "models.add" }));
  fireEvent.change(screen.getByLabelText("models.apiKey"), {
    target: { value: "unsaved-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Second" }));

  expect(screen.queryByLabelText("models.apiKey")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "models.add" }));
  expect(screen.getByLabelText("models.apiKey")).toHaveValue("");
});
