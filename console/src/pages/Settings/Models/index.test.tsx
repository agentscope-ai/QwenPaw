/**
 * Models settings page — provider directory covering tab switching, search
 * filtering, cloud/local grouping, provider-group variant selection,
 * URL-param driven modal auto-open, refresh and the add-provider / default
 * LLM modals.
 *
 * The heavy child cards and modals are stubbed so the page's own data-flow
 * logic (grouping, filtering, state transitions) is what gets exercised.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import { renderWithProviders } from "@/test/common_setup";
import type { ProviderInfo } from "../../../api/types/provider";

const providersMock = vi.hoisted(() => ({
  providers: [] as ProviderInfo[],
  activeModels: null as unknown,
  loading: false,
  error: null as string | null,
  fetchAll: vi.fn(),
}));

vi.mock("./useProviders", () => ({
  useProviders: () => providersMock,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

// Stub the heavy children; expose data-testids for assertions.
vi.mock("./components", () => {
  return {
    LoadingState: ({
      message,
      error,
      onRetry,
    }: {
      message: string;
      error?: boolean;
      onRetry?: () => void;
    }) =>
      React.createElement(
        "div",
        { "data-testid": "loading-state" },
        String(message),
        error
          ? React.createElement(
              "button",
              { type: "button", onClick: () => onRetry?.() },
              "retry",
            )
          : null,
      ),
    ProviderCard: ({ provider }: Record<string, unknown>) =>
      React.createElement(
        "div",
        { "data-testid": `provider-card:${(provider as ProviderInfo).id}` },
        (provider as ProviderInfo).name,
      ),
    ProviderGroupCard: ({ group }: Record<string, unknown>) =>
      React.createElement(
        "div",
        {
          "data-testid": `group-card:${
            (group as { groupKey: string }).groupKey
          }`,
        },
        (group as { groupName: string }).groupName,
      ),
    CustomProviderModal: ({ open }: Record<string, unknown>) =>
      open
        ? React.createElement("div", { "data-testid": "custom-provider-modal" })
        : null,
    ModelsSection: () =>
      React.createElement("div", { "data-testid": "models-section" }),
    ProviderConfigModal: ({ provider }: Record<string, unknown>) =>
      React.createElement(
        "div",
        {
          "data-testid": `config-modal:${(provider as ProviderInfo).id}`,
        },
        `config:${(provider as ProviderInfo).name}`,
      ),
    ModelManageModal: ({ provider }: Record<string, unknown>) =>
      React.createElement(
        "div",
        {
          "data-testid": `manage-modal:${(provider as ProviderInfo).id}`,
        },
        `manage:${(provider as ProviderInfo).name}`,
      ),
  };
});

vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const antd = await import("antd");
  const original = (await importOriginal()) as Record<string, unknown>;
  return {
    ...original,
    Input: antd.Input,
    Button: antd.Button,
    Modal: antd.Modal,
  };
});

vi.mock("./components/ProviderIconComponent", () => ({
  ProviderIcon: ({ providerId }: Record<string, unknown>) =>
    React.createElement("span", {
      "data-testid": `icon:${providerId}`,
    }),
}));

import ModelsPage from "./index";

function makeProvider(overrides: Partial<ProviderInfo> = {}): ProviderInfo {
  return {
    id: "prov-1",
    name: "Provider One",
    models: [],
    extra_models: [],
    is_custom: false,
    is_local: false,
    require_api_key: true,
    api_key: "",
    base_url: "",
    generate_kwargs: {},
    chat_model: "OpenAIChatModel",
    ...overrides,
  } as ProviderInfo;
}

function setProviders(list: ProviderInfo[], active: unknown = null) {
  providersMock.providers = list;
  providersMock.activeModels = active;
  providersMock.loading = false;
  providersMock.error = null;
}

describe("ModelsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    setProviders([]);
  });

  it("shows the loading state while fetching", () => {
    providersMock.loading = true;
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });
    expect(screen.getByTestId("loading-state")).toBeInTheDocument();
  });

  it("shows the error state with a retry action", () => {
    providersMock.error = "fetch broke";
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });
    expect(screen.getByText("fetch broke")).toBeInTheDocument();
    fireEvent.click(screen.getByText("retry"));
    expect(providersMock.fetchAll).toHaveBeenCalled();
  });

  it("renders cloud providers into configured and available sections", () => {
    setProviders([
      makeProvider({ id: "openai", name: "OpenAI", api_key: "sk-x" }),
      makeProvider({ id: "anthropic", name: "Anthropic", api_key: "" }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    expect(screen.getByTestId("provider-card:openai")).toBeInTheDocument();
    // Anthropic (not configured) lives in the available grid
    expect(screen.getByTestId("icon:anthropic")).toBeInTheDocument();
  });

  it("shows the empty configured state with a go-configure button", () => {
    setProviders([
      makeProvider({ id: "only-avail", name: "Only Avail", api_key: "" }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });
    expect(screen.getByText("models.noConfigured")).toBeInTheDocument();
    expect(screen.getByText("models.goConfigureBtn")).toBeInTheDocument();
  });

  it("switches between cloud and local tabs", async () => {
    const user = userEvent.setup();
    setProviders([
      makeProvider({ id: "openai", name: "OpenAI", api_key: "sk-x" }),
      makeProvider({
        id: "loc",
        name: "Local Thing",
        is_local: true,
        require_api_key: false,
      }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    // Default tab is cloud
    expect(screen.getByTestId("provider-card:openai")).toBeInTheDocument();

    await user.click(screen.getByText(/models\.localCustomGroup/));
    expect(screen.getByTestId("provider-card:loc")).toBeInTheDocument();
    expect(localStorage.getItem("models_tab")).toBe("local");
  });

  it("restores the last-used tab from localStorage", () => {
    localStorage.setItem("models_tab", "local");
    setProviders([
      makeProvider({
        id: "loc",
        name: "Local Thing",
        is_local: true,
        require_api_key: false,
      }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });
    expect(screen.getByTestId("provider-card:loc")).toBeInTheDocument();
  });

  it("filters providers by the search query", async () => {
    const user = userEvent.setup();
    setProviders([
      makeProvider({ id: "openai", name: "OpenAI", api_key: "sk-x" }),
      makeProvider({ id: "anthropic", name: "Anthropic", api_key: "sk-y" }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    const search = screen.getByPlaceholderText("models.searchPlaceholder");
    await user.click(search);
    await user.type(search, "openai");

    await waitFor(() =>
      expect(screen.getByTestId("provider-card:openai")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("provider-card:anthropic"),
    ).not.toBeInTheDocument();
  });

  it("refreshes providers via the refresh button", async () => {
    const user = userEvent.setup();
    setProviders([
      makeProvider({ id: "openai", name: "OpenAI", api_key: "sk-x" }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    await user.click(screen.getByTitle("common.refresh"));
    expect(providersMock.fetchAll).toHaveBeenCalled();
  });

  it("opens the add-provider modal", async () => {
    const user = userEvent.setup();
    setProviders([]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    await user.click(screen.getByText("models.addProvider"));
    expect(screen.getByTestId("custom-provider-modal")).toBeInTheDocument();
  });

  it("opens the provider config modal from an available item", async () => {
    const user = userEvent.setup();
    setProviders([
      makeProvider({ id: "only-avail", name: "Only Avail", api_key: "" }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    await user.click(screen.getByTestId("icon:only-avail"));
    await waitFor(() =>
      expect(screen.getByTestId("config-modal:only-avail")).toBeInTheDocument(),
    );
  });

  it("opens the variant selector for multi-provider groups", async () => {
    const user = userEvent.setup();
    setProviders([
      makeProvider({
        id: "azure-a",
        name: "Azure A",
        provider_group: "azure",
        provider_group_name: "Azure",
        api_key: "",
      }),
      makeProvider({
        id: "azure-b",
        name: "Azure B",
        provider_group: "azure",
        provider_group_name: "Azure",
        api_key: "",
      }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    await user.click(screen.getByTestId("icon:azure-a"));
    await waitFor(() =>
      expect(screen.getByText(/models\.selectVariant/)).toBeInTheDocument(),
    );
  });

  it("auto-opens the config modal from the provider URL param", async () => {
    setProviders([makeProvider({ id: "openai", name: "OpenAI", api_key: "" })]);
    renderWithProviders(<ModelsPage />, {
      initialEntries: ["/models?provider=openai"],
    });

    await waitFor(() =>
      expect(screen.getByTestId("config-modal:openai")).toBeInTheDocument(),
    );
  });

  it("auto-opens the manage modal when manageModels=true", async () => {
    setProviders([makeProvider({ id: "openai", name: "OpenAI", api_key: "" })]);
    renderWithProviders(<ModelsPage />, {
      initialEntries: ["/models?provider=openai&manageModels=true"],
    });

    await waitFor(() =>
      expect(screen.getByTestId("manage-modal:openai")).toBeInTheDocument(),
    );
  });

  it("renders the default LLM pill with the active model", () => {
    setProviders(
      [makeProvider({ id: "openai", name: "OpenAI", api_key: "sk-x" })],
      {
        active_llm: { provider_id: "openai", model: "gpt-x" },
      },
    );
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });
    expect(screen.getByText(/models\.defaultLlm/)).toBeInTheDocument();
    expect(screen.getByText(/gpt-x/)).toBeInTheDocument();
  });

  it("groups configured cloud providers by provider_group", () => {
    setProviders([
      makeProvider({
        id: "azure-a",
        name: "Azure A",
        provider_group: "azure",
        provider_group_name: "Azure",
        api_key: "sk-x",
      }),
      makeProvider({
        id: "azure-b",
        name: "Azure B",
        provider_group: "azure",
        provider_group_name: "Azure",
        api_key: "",
      }),
    ]);
    renderWithProviders(<ModelsPage />, { initialEntries: ["/models"] });

    // The whole group is pulled into configured because one variant is
    expect(screen.getByTestId("group-card:azure")).toBeInTheDocument();
  });
});
