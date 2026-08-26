import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ModelSelector from "./index";
import { AgentModelSettings } from "./AgentModelSettings";
import { useTurnUsageStore } from "../turnUsageStore";

const agentStoreState = vi.hoisted(() => ({ selectedAgent: "default" }));
const navigateMock = vi.hoisted(() => vi.fn());

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: vi.fn(),
    getActiveModels: vi.fn(),
    setActiveLlm: vi.fn(),
    addModel: vi.fn(),
    setModelVisibility: vi.fn(),
  },
}));

vi.mock("@/api/modules/agents", () => ({
  agentsApi: {
    getAgent: vi.fn(),
    updateAgent: vi.fn(),
    updateModelSettings: vi.fn(),
  },
}));

vi.mock("@/utils/freeModelSwitchWarning", () => ({
  confirmFreeModelSwitch: vi.fn(),
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({
    selectedAgent: agentStoreState.selectedAgent,
  })),
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("./OAuthConfirmModal", () => ({
  OAuthConfirmModal: ({
    open,
    onSuccess,
    onCancel,
  }: {
    open: boolean;
    onSuccess: () => void;
    onCancel: () => void;
  }) =>
    open ? (
      <div>
        <button type="button" onClick={onSuccess}>
          oauth-success
        </button>
        <button type="button" onClick={onCancel}>
          oauth-cancel
        </button>
      </div>
    ) : null,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      key === "modelSelector.viewMore"
        ? `${key} (${options?.count ?? 0})`
        : key,
  }),
}));

vi.mock("lucide-react", () => ({
  AlertTriangle: () => "AlertTriangle",
  Check: () => "Check",
  ChevronDown: () => "ChevronDown",
  ChevronUp: () => "ChevronUp",
  Eye: () => "Eye",
  EyeOff: () => "EyeOff",
  ExternalLink: () => "ExternalLink",
  GitBranch: () => "GitBranch",
  Link: () => "Link",
  Loader2: () => "Loader2",
  LoaderCircle: () => "LoaderCircle",
  Plus: () => "Plus",
  Search: () => "Search",
  Save: () => "Save",
  Settings: () => "Settings",
  Settings2: () => "Settings2",
  Trash2: () => "Trash2",
  XCircle: () => "XCircle",
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

import { providerApi } from "@/api/modules/provider";
import { agentsApi } from "@/api/modules/agents";
import type { ActiveModelsInfo } from "@/api/types";
import { confirmFreeModelSwitch } from "@/utils/freeModelSwitchWarning";

const mockProvider = {
  id: "openai",
  name: "OpenAI",
  api_key: "sk-xxx",
  api_key_prefix: "",
  chat_model: "OpenAIChatModel",
  require_api_key: true,
  base_url: "",
  is_custom: false,
  is_local: false,
  support_model_discovery: false,
  support_connection_check: false,
  freeze_url: false,
  generate_kwargs: {},
  models: [
    {
      id: "gpt-4",
      name: "GPT-4",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      generate_kwargs: {},
      max_tokens: 8192,
      max_input_length: 32768,
      relay_reasoning: true,
      thinking_enabled: null,
      thinking_budget: null,
      reasoning_effort: null,
      is_recommended: true,
    },
    {
      id: "gpt-3.5-turbo",
      name: "GPT-3.5 Turbo",
      supports_multimodal: false,
      supports_image: false,
      supports_video: false,
      generate_kwargs: {},
      max_tokens: 4096,
      max_input_length: 16384,
      relay_reasoning: true,
      thinking_enabled: null,
      thinking_budget: null,
      reasoning_effort: null,
      is_recommended: true,
    },
  ],
  extra_models: [],
};

const mockActiveModels = {
  active_llm: { provider_id: "openai", model: "gpt-4" },
};

function setupDefaultMocks() {
  agentStoreState.selectedAgent = "default";
  vi.mocked(providerApi.listProviders).mockResolvedValue([mockProvider]);
  vi.mocked(providerApi.getActiveModels).mockResolvedValue(mockActiveModels);
  vi.mocked(providerApi.setActiveLlm).mockResolvedValue({ active_llm: null });
  vi.mocked(providerApi.addModel).mockResolvedValue(mockProvider);
  vi.mocked(providerApi.setModelVisibility).mockResolvedValue(mockProvider);
  vi.mocked(confirmFreeModelSwitch).mockResolvedValue(true);
  vi.mocked(agentsApi.getAgent).mockResolvedValue({
    id: "default",
    name: "Default",
    fallback_models: [],
    fallback_policy: { enabled: true, target_scope: "configured" },
    subagent_model: null,
    thinking_level: "inherit",
  });
  vi.mocked(agentsApi.updateModelSettings).mockImplementation(
    async (_id, settings) => ({
      id: "default",
      name: "Default",
      ...settings,
    }),
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ModelSelector", () => {
  beforeEach(() => {
    localStorage.clear();
    useTurnUsageStore.getState().invalidateTurn();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("displays current active model name on trigger button after loading", async () => {
    renderWithProviders(<ModelSelector />);
    expect((await screen.findAllByText("GPT-4"))[0]).toBeInTheDocument();
  });

  it("marks the active free model on the trigger button", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: [{ ...mockProvider.models[0], is_free: true }],
      },
    ]);
    renderWithProviders(<ModelSelector />);

    const trigger = await screen.findByRole("button", {
      name: "chat.modelSelectTooltip",
    });
    await waitFor(() => {
      expect(trigger).toHaveTextContent("modelSelector.free");
      expect(trigger.querySelector('[class*="freeTag"]')).toBeInTheDocument();
    });
  });

  it("does not mark a paid active model as free", async () => {
    renderWithProviders(<ModelSelector />);

    const trigger = await screen.findByRole("button", {
      name: "chat.modelSelectTooltip",
    });
    expect(trigger).not.toHaveTextContent("modelSelector.free");
    expect(trigger.querySelector('[class*="freeTag"]')).toBeNull();
  });

  it("keeps advanced model controls out of the release UI", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-new",
      name: "GPT New",
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, discovered_models: [candidate] },
    ]);
    useTurnUsageStore.getState().setSnapshot({
      usage: {
        provider_id: "openai",
        model_name: "gpt-3.5-turbo",
        total_tokens: 3,
      },
      context_usage: null,
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");
    const trigger = screen.getByRole("button", {
      name: "chat.modelSelectTooltip",
    });

    expect(trigger).toHaveTextContent("GPT-4");
    expect(
      screen.queryByLabelText("modelSelector.fallbackActive"),
    ).not.toBeInTheDocument();

    await user.click(trigger);

    expect(
      screen.getByPlaceholderText("modelSelector.searchModels"),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "PRO" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "FREE" })).toBeInTheDocument();
    expect(
      screen.queryByText("modelSelector.proBannerText"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "modelSelector.showAll" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "modelSelector.showRecommended" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /modelSelector.availableToAdd/,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    ).not.toBeInTheDocument();
  });

  it("displays i18n key when there is no active model", async () => {
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: null,
    });
    renderWithProviders(<ModelSelector />);
    expect(
      (await screen.findAllByText("modelSelector.selectModel"))[0],
    ).toBeInTheDocument();
  });

  it("displays bare model id when active model is outside the eligible list", async () => {
    // provider has no api_key configured, so it is excluded from eligible list
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, api_key: "" },
    ]);
    renderWithProviders(<ModelSelector />);
    expect((await screen.findAllByText("gpt-4"))[0]).toBeInTheDocument();
  });

  it("calls listProviders and getActiveModels on mount", async () => {
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");
    expect(providerApi.listProviders).toHaveBeenCalledOnce();
    expect(providerApi.getActiveModels).toHaveBeenCalledWith({
      scope: "effective",
      agent_id: "default",
    });
  });

  it("ignores an active-model response from the previously selected agent", async () => {
    const oldAgentResponse = deferred<ActiveModelsInfo>();
    vi.mocked(providerApi.getActiveModels).mockImplementation((params) =>
      params?.agent_id === "agent-b"
        ? Promise.resolve({
            active_llm: { provider_id: "openai", model: "gpt-3.5-turbo" },
            effective_max_input_length: 16384,
          })
        : oldAgentResponse.promise,
    );

    const view = renderWithProviders(<ModelSelector />);
    agentStoreState.selectedAgent = "agent-b";
    view.rerender(<ModelSelector />);

    expect(
      (await screen.findAllByText("GPT-3.5 Turbo"))[0],
    ).toBeInTheDocument();

    oldAgentResponse.resolve({
      ...mockActiveModels,
      effective_max_input_length: 32768,
    });
    await waitFor(() => {
      expect(screen.getAllByText("GPT-3.5 Turbo").length).toBeGreaterThan(0);
    });
    expect(screen.queryByText("GPT-4")).not.toBeInTheDocument();
    expect(useTurnUsageStore.getState().activeMaxInputLength).toBe(16384);
  });

  it("clicking trigger button opens dropdown and shows provider list", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);

    expect(await screen.findByText("OpenAI")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "chat.modelSelectTooltip" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("clicking a model calls setActiveLlm with correct parameters", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    const gpt35 = await screen.findByText("GPT-3.5 Turbo");
    await user.click(gpt35);

    expect(providerApi.setActiveLlm).toHaveBeenCalledWith({
      provider_id: "openai",
      model: "gpt-3.5-turbo",
      scope: "agent",
      agent_id: "default",
    });
  });

  it("activates the selected model after OAuth succeeds", async () => {
    const oauthProvider = {
      ...mockProvider,
      id: "oauth-provider",
      name: "OAuth Provider",
      api_key: "",
      base_url: "https://oauth.example.com",
      require_api_key: false,
      supports_oauth: true,
      oauth_connected: false,
    };
    vi.mocked(providerApi.listProviders)
      .mockResolvedValueOnce([oauthProvider])
      .mockResolvedValueOnce([{ ...oauthProvider, oauth_connected: true }]);
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: {
        provider_id: oauthProvider.id,
        model: "gpt-4",
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(await screen.findByText("GPT-3.5 Turbo"));
    await user.click(await screen.findByText("oauth-success"));

    await waitFor(() => {
      expect(providerApi.setActiveLlm).toHaveBeenCalledWith({
        provider_id: oauthProvider.id,
        model: "gpt-3.5-turbo",
        scope: "agent",
        agent_id: "default",
      });
    });
    expect(navigateMock).not.toHaveBeenCalled();
    expect(localStorage.getItem("qwenpaw_model_selector_recent")).toBe(
      JSON.stringify(["oauth-provider:gpt-3.5-turbo"]),
    );
  });

  it("clears the pending model when OAuth is cancelled", async () => {
    const oauthProvider = {
      ...mockProvider,
      id: "oauth-provider",
      api_key: "",
      base_url: "https://oauth.example.com",
      require_api_key: false,
      supports_oauth: true,
      oauth_connected: false,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([oauthProvider]);
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: {
        provider_id: oauthProvider.id,
        model: "gpt-4",
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(await screen.findByText("GPT-3.5 Turbo"));
    await user.click(await screen.findByText("oauth-cancel"));

    expect(providerApi.setActiveLlm).not.toHaveBeenCalled();
    expect(screen.queryByText("oauth-cancel")).not.toBeInTheDocument();
  });

  it("opens provider management if the OAuth target model disappeared", async () => {
    const oauthProvider = {
      ...mockProvider,
      id: "oauth-provider",
      api_key: "",
      base_url: "https://oauth.example.com",
      require_api_key: false,
      supports_oauth: true,
      oauth_connected: false,
    };
    vi.mocked(providerApi.listProviders)
      .mockResolvedValueOnce([oauthProvider])
      .mockResolvedValueOnce([
        {
          ...oauthProvider,
          oauth_connected: true,
          models: [oauthProvider.models[0]],
        },
      ]);
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: {
        provider_id: oauthProvider.id,
        model: "gpt-4",
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(await screen.findByText("GPT-3.5 Turbo"));
    await user.click(await screen.findByText("oauth-success"));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith(
        "/models?provider=oauth-provider&manageModels=true",
      );
    });
    expect(providerApi.setActiveLlm).not.toHaveBeenCalled();
  });

  it("publishes the backend-resolved context window after a model switch", async () => {
    vi.mocked(providerApi.setActiveLlm).mockResolvedValue({
      active_llm: {
        provider_id: "openai",
        model: "gpt-3.5-turbo",
      },
      effective_max_input_length: 65536,
    });
    const switched = vi.fn();
    window.addEventListener("model-switched", switched);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(await screen.findByText("GPT-3.5 Turbo"));

    await waitFor(() => expect(switched).toHaveBeenCalledOnce());
    const event = switched.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toEqual({
      maxInputLength: 65536,
    });
    window.removeEventListener("model-switched", switched);
  });

  it("ignores a model-switch response for the previously selected agent", async () => {
    const switchResponse = deferred<ActiveModelsInfo>();
    vi.mocked(providerApi.setActiveLlm).mockReturnValue(switchResponse.promise);
    const user = userEvent.setup();
    const view = renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(await screen.findByText("GPT-3.5 Turbo"));
    expect(providerApi.setActiveLlm).toHaveBeenCalledWith({
      provider_id: "openai",
      model: "gpt-3.5-turbo",
      scope: "agent",
      agent_id: "default",
    });

    agentStoreState.selectedAgent = "agent-b";
    view.rerender(<ModelSelector />);
    switchResponse.resolve({
      active_llm: {
        provider_id: "openai",
        model: "gpt-3.5-turbo",
      },
      effective_max_input_length: 65536,
    });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "chat.modelSelectTooltip" }),
      ).toHaveTextContent("GPT-4");
    });
    expect(
      screen.getByRole("button", { name: "chat.modelSelectTooltip" }),
    ).not.toHaveTextContent("GPT-3.5 Turbo");
    expect(localStorage.getItem("qwenpaw_model_selector_recent")).toBeNull();
  });

  it("publishes the backend-resolved context window after loading active models", async () => {
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      ...mockActiveModels,
      effective_max_input_length: 262144,
    });
    const switched = vi.fn();
    window.addEventListener("model-switched", switched);
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await waitFor(() => expect(switched).toHaveBeenCalledOnce());
    const event = switched.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toEqual({
      maxInputLength: 262144,
    });
    window.removeEventListener("model-switched", switched);
  });

  it("clicking the already active model does not call setActiveLlm", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    const gpt4Items = await screen.findAllByText("GPT-4");
    await user.click(gpt4Items[gpt4Items.length - 1]);

    expect(providerApi.setActiveLlm).not.toHaveBeenCalled();
  });

  it("dropdown shows empty state when no providers are available", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([]);
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: null,
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("modelSelector.selectModel");

    await user.click(screen.getAllByText("modelSelector.selectModel")[0]);

    expect(
      await screen.findByText("modelSelector.noConfiguredModels"),
    ).toBeInTheDocument();
  });

  it("keeps partial data visible and offers retry when loading partly fails", async () => {
    vi.mocked(providerApi.getActiveModels).mockRejectedValue(
      new Error("active unavailable"),
    );
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("modelSelector.selectModel");

    await user.click(
      screen.getByRole("button", { name: "chat.modelSelectTooltip" }),
    );

    expect(await screen.findByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "modelSelector.partialLoadFailed",
    );
    expect(
      screen.getByRole("button", { name: "modelSelector.retry" }),
    ).toBeInTheDocument();
  });

  it("still displays original active model after setActiveLlm failure", async () => {
    vi.mocked(providerApi.setActiveLlm).mockRejectedValue(
      new Error("API error"),
    );
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    const gpt35 = await screen.findByText("GPT-3.5 Turbo");
    await user.click(gpt35);

    // GPT-4 may appear in two places when dropdown is still open (trigger + dropdown item)
    await waitFor(() => {
      expect(screen.getAllByText("GPT-4").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows five configured PRO models then expands all remaining models", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: Array.from({ length: 8 }, (_, index) => ({
          ...mockProvider.models[0],
          id: `model-${index}`,
          name: `Model ${index}`,
          is_recommended: index % 2 === 0,
        })),
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("gpt-4");

    await user.click(screen.getAllByText("gpt-4")[0]);

    expect(await screen.findByText("Model 0")).toBeInTheDocument();
    expect(screen.getByText("Model 4")).toBeInTheDocument();
    expect(screen.queryByText("Model 5")).not.toBeInTheDocument();
    const viewMore = screen.getByRole("button", {
      name: "modelSelector.viewMore (3)",
    });

    await user.click(viewMore);

    expect(await screen.findByText("Model 5")).toBeInTheDocument();
    expect(screen.getByText("Model 7")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "modelSelector.viewMore (3)",
      }),
    ).not.toBeInTheDocument();
  });

  it("expands each provider by default and limits each to five models", async () => {
    localStorage.setItem(
      "qwenpaw_model_selector_collapsed",
      JSON.stringify(["openai", "anthropic"]),
    );
    const openAiModels = Array.from({ length: 6 }, (_, index) => ({
      ...mockProvider.models[0],
      id: `openai-model-${index}`,
      name: `OpenAI Model ${index}`,
      is_recommended: false,
    }));
    const anthropicModels = Array.from({ length: 6 }, (_, index) => ({
      ...mockProvider.models[0],
      id: `anthropic-model-${index}`,
      name: `Anthropic Model ${index}`,
      is_recommended: false,
    }));
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, models: openAiModels },
      {
        ...mockProvider,
        id: "anthropic",
        name: "Anthropic",
        models: anthropicModels,
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await user.click(
      await screen.findByRole("button", {
        name: "chat.modelSelectTooltip",
      }),
    );
    await screen.findByText("OpenAI Model 0");

    expect(screen.getByText("OpenAI").closest("button")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Anthropic").closest("button")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("OpenAI Model 4")).toBeInTheDocument();
    expect(screen.queryByText("OpenAI Model 5")).not.toBeInTheDocument();
    expect(screen.getByText("Anthropic Model 4")).toBeInTheDocument();
    expect(screen.queryByText("Anthropic Model 5")).not.toBeInTheDocument();
  });

  it("does not persist provider collapse state", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await user.click(
      await screen.findByRole("button", {
        name: "chat.modelSelectTooltip",
      }),
    );

    await user.click(screen.getByText("OpenAI").closest("button")!);

    expect(localStorage.getItem("qwenpaw_model_selector_collapsed")).toBeNull();
  });

  it("loads large provider lists step by step instead of all at once", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: Array.from({ length: 105 }, (_, index) => ({
          ...mockProvider.models[0],
          id: `large-model-${index}`,
          name: `Large Model ${index}`,
          is_recommended: false,
        })),
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await user.click(
      await screen.findByRole("button", {
        name: "chat.modelSelectTooltip",
      }),
    );

    // Button shows the next batch size (20), not the full remaining count
    const viewMore = await screen.findByRole("button", {
      name: "modelSelector.viewMore (20)",
    });
    expect(viewMore).toBeInTheDocument();
    expect(screen.queryByText("Large Model 5")).not.toBeInTheDocument();

    await user.click(viewMore);

    // One click reveals one more batch (5 + 20 = 25), not everything
    expect(await screen.findByText("Large Model 24")).toBeInTheDocument();
    expect(screen.queryByText("Large Model 25")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "modelSelector.viewMore (20)",
      }),
    ).toBeInTheDocument();

    // Keep clicking until all models are revealed and the button disappears
    for (let i = 0; i < 4; i += 1) {
      await user.click(
        screen.getByRole("button", {
          name: /modelSelector\.viewMore/,
        }),
      );
    }
    expect(await screen.findByText("Large Model 104")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /modelSelector\.viewMore/,
      }),
    ).not.toBeInTheDocument();
  });

  it("shows configured PRO models even when none are recommended", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: mockProvider.models.map((model) => ({
          ...model,
          is_recommended: false,
        })),
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);

    expect(screen.getAllByText("GPT-4").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("GPT-3.5 Turbo")).toBeInTheDocument();
  });

  it("does not render model pin controls", async () => {
    localStorage.setItem(
      "qwenpaw_model_selector_pinned",
      JSON.stringify(["openai:gpt-3.5-turbo"]),
    );
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: [
          ...mockProvider.models.map((model) => ({
            ...model,
            is_recommended: false,
          })),
          {
            ...mockProvider.models[0],
            id: "added-model",
            name: "Added Model",
            is_recommended: false,
          },
        ],
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);

    expect(
      screen.queryByRole("button", { name: "modelSelector.pinModel" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Added Model")).toBeInTheDocument();
  });

  it("keeps recent models visible without showing all models", async () => {
    localStorage.setItem(
      "qwenpaw_model_selector_recent",
      JSON.stringify(["openai:gpt-3.5-turbo"]),
    );
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: mockProvider.models.map((model) => ({
          ...model,
          is_recommended: false,
        })),
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);

    expect(await screen.findByText("GPT-3.5 Turbo")).toBeInTheDocument();
  });

  it("searches all configured models beyond the recommendation limit", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: Array.from({ length: 8 }, (_, index) => ({
          ...mockProvider.models[0],
          id: `model-${index}`,
          name: `Model ${index}`,
        })),
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("gpt-4");
    await user.click(screen.getAllByText("gpt-4")[0]);

    await user.type(
      screen.getByPlaceholderText("modelSelector.searchModels"),
      "Model 7",
    );

    expect(await screen.findByText("Model 7")).toBeInTheDocument();
  });

  it("adds a discovery candidate before activating it", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-new",
      name: "GPT New",
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, discovered_models: [candidate] },
    ]);
    const calls: string[] = [];
    vi.mocked(providerApi.addModel).mockImplementation(async () => {
      calls.push("add");
      return { ...mockProvider, extra_models: [candidate] };
    });
    vi.mocked(providerApi.setActiveLlm).mockImplementation(async () => {
      calls.push("activate");
      return { active_llm: null };
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.type(
      screen.getByPlaceholderText("modelSelector.searchModels"),
      "GPT New",
    );

    await user.click(
      await screen.findByRole("button", {
        name: "modelSelector.addAndUse",
      }),
    );

    await waitFor(() => expect(calls).toEqual(["add", "activate"]));
    expect(providerApi.addModel).toHaveBeenCalledWith(
      "openai",
      expect.objectContaining({ id: "gpt-new" }),
    );
  });

  it("collapses available models by default and toggles the section", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-new",
      name: "GPT New",
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, discovered_models: [candidate] },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);

    const toggle = await screen.findByRole("button", {
      name: /modelSelector.availableToAdd/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("GPT New")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("GPT New")).toBeInTheDocument();
    const candidateBody = document.getElementById(
      toggle.getAttribute("aria-controls") ?? "",
    );
    expect(candidateBody?.parentElement).toBe(toggle.parentElement);

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("GPT New")).not.toBeInTheDocument();
  });

  it("shows matching available models during search then restores collapse", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-new",
      name: "GPT New",
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, discovered_models: [candidate] },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);

    const searchInput = screen.getByPlaceholderText(
      "modelSelector.searchModels",
    );
    await user.type(searchInput, "GPT New");

    const toggle = await screen.findByRole("button", {
      name: /modelSelector.availableToAdd/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toBeDisabled();
    expect(await screen.findByText("GPT New")).toBeInTheDocument();

    await user.clear(searchInput);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).not.toBeDisabled();
    expect(screen.queryByText("GPT New")).not.toBeInTheDocument();
  });

  it("shows free discovery candidates without requiring search", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-free",
      name: "GPT Free",
      is_free: true,
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        is_free_tier: true,
        discovered_models: [candidate],
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(screen.getByRole("tab", { name: "FREE" }));

    const toggle = await screen.findByRole("button", {
      name: /modelSelector.availableToAdd/,
    });
    expect(screen.queryByText("GPT Free")).not.toBeInTheDocument();
    await user.click(toggle);

    expect(await screen.findByText("GPT Free")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "modelSelector.addAndUse" }),
    ).toBeInTheDocument();
  });

  it("shows every free model from a configured free provider", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        id: "opencode",
        name: "OpenCode",
        is_free_tier: true,
        models: [
          {
            ...mockProvider.models[0],
            id: "opencode-free-one",
            name: "OpenCode Free One",
            is_free: true,
          },
          {
            ...mockProvider.models[1],
            id: "opencode-free-two",
            name: "OpenCode Free Two",
            is_free: true,
          },
          {
            ...mockProvider.models[1],
            id: "opencode-paid-model",
            name: "OpenCode Paid Model",
            is_free: false,
          },
        ],
      },
    ]);
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: {
        provider_id: "opencode",
        model: "opencode-free-one",
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await user.click(
      await screen.findByRole("button", {
        name: "chat.modelSelectTooltip",
      }),
    );

    await user.click(screen.getByRole("tab", { name: "FREE" }));
    expect(
      (await screen.findAllByText("OpenCode Free One")).length,
    ).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText("OpenCode Free Two")).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("OpenCode Paid Model")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "PRO" }));
    expect(
      (await screen.findAllByText("OpenCode Free One")).length,
    ).toBeGreaterThan(0);
    expect(
      (await screen.findAllByText("OpenCode Free Two")).length,
    ).toBeGreaterThan(0);
    expect(await screen.findByText("OpenCode Paid Model")).toBeInTheDocument();
  });

  it("does not show paid discovery candidates in the free tab search", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-paid-candidate",
      name: "GPT Paid Candidate",
      is_free: false,
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, is_free_tier: true, discovered_models: [candidate] },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(screen.getByRole("tab", { name: "FREE" }));
    await user.type(
      screen.getByPlaceholderText("modelSelector.searchModels"),
      "GPT Paid Candidate",
    );

    expect(screen.queryByText("GPT Paid Candidate")).not.toBeInTheDocument();
  });

  it("does not activate a discovery candidate when adding fails", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        discovered_models: [
          {
            ...mockProvider.models[0],
            id: "gpt-new",
            name: "GPT New",
            source: "discovered" as const,
          },
        ],
      },
    ]);
    vi.mocked(providerApi.addModel).mockRejectedValue(new Error("blocked"));
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.type(
      screen.getByPlaceholderText("modelSelector.searchModels"),
      "GPT New",
    );

    await user.click(
      await screen.findByRole("button", {
        name: "modelSelector.addAndUse",
      }),
    );

    await waitFor(() => expect(providerApi.addModel).toHaveBeenCalledOnce());
    expect(providerApi.setActiveLlm).not.toHaveBeenCalled();
  });

  it("does not add a free discovery candidate when switching is cancelled", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-free",
      name: "GPT Free",
      is_free: true,
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, discovered_models: [candidate] },
    ]);
    vi.mocked(confirmFreeModelSwitch).mockResolvedValue(false);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(screen.getByRole("tab", { name: "FREE" }));
    await user.type(
      screen.getByPlaceholderText("modelSelector.searchModels"),
      "GPT Free",
    );

    await user.click(
      await screen.findByRole("button", {
        name: "modelSelector.addAndUse",
      }),
    );

    expect(confirmFreeModelSwitch).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: expect.objectContaining({ id: "openai" }),
        model: expect.objectContaining({ id: "gpt-free" }),
      }),
    );
    expect(providerApi.addModel).not.toHaveBeenCalled();
    expect(providerApi.setActiveLlm).not.toHaveBeenCalled();
  });

  it("restores a hidden discovery candidate", async () => {
    const candidate = {
      ...mockProvider.models[0],
      id: "gpt-hidden",
      name: "GPT Hidden",
      source: "discovered" as const,
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        discovered_models: [candidate],
        hidden_model_ids: [candidate.id],
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(await screen.findByText("modelSelector.hiddenModels"));
    await user.click(
      await screen.findByRole("button", {
        name: "modelSelector.restoreModel",
      }),
    );

    expect(providerApi.setModelVisibility).toHaveBeenCalledWith(
      "openai",
      "gpt-hidden",
      false,
    );
  });

  it("saves ordered fallback and agent-level model settings", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      {
        ...mockProvider,
        models: [
          {
            ...mockProvider.models[0],
            thinking_enabled: true,
            supports_agent_thinking: true,
          },
          mockProvider.models[1],
        ],
      },
    ]);
    vi.mocked(agentsApi.updateModelSettings).mockImplementation(
      async (_agentId, settings) => ({
        id: "default",
        name: "Default",
        ...settings,
        description: "preserved by backend merge",
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(
      await screen.findByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );

    await user.click(
      await screen.findByRole("combobox", {
        name: "modelSelector.thinkingLevel",
      }),
    );
    const thinkingOptions = screen.getAllByText("modelSelector.thinking.high");
    await user.click(thinkingOptions[thinkingOptions.length - 1]);
    await user.click(
      screen.getByRole("combobox", {
        name: "modelSelector.subagentModel",
      }),
    );
    const subagentOptions = screen.getAllByText("OpenAI / GPT-3.5 Turbo");
    await user.click(subagentOptions[subagentOptions.length - 1]);
    await user.click(
      screen.getByRole("combobox", {
        name: "modelSelector.chooseFallback",
      }),
    );
    const fallbackOptions = screen.getAllByText("OpenAI / GPT-3.5 Turbo");
    await user.click(fallbackOptions[fallbackOptions.length - 1]);
    await user.click(
      screen.getByRole("button", { name: "modelSelector.addFallback" }),
    );
    await user.click(screen.getByRole("button", { name: /common.save/ }));

    await waitFor(() =>
      expect(agentsApi.updateModelSettings).toHaveBeenCalledOnce(),
    );
    expect(agentsApi.updateModelSettings).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        fallback_models: [{ provider_id: "openai", model: "gpt-3.5-turbo" }],
        fallback_policy: {
          enabled: true,
          target_scope: "configured",
        },
        subagent_model: {
          provider_id: "openai",
          model: "gpt-3.5-turbo",
        },
        thinking_level: "high",
      }),
    );
  });

  it("does not send a cached active model when saving settings", async () => {
    const user = userEvent.setup();
    const settingsProps = {
      providers: [
        {
          id: mockProvider.id,
          name: mockProvider.name,
          models: mockProvider.models,
        },
      ],
      activeProviderId: "openai",
      activeModelId: "gpt-4",
    };
    const view = renderWithProviders(
      <AgentModelSettings agentId="default" {...settingsProps} />,
    );
    await user.click(
      screen.getByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );
    await screen.findByLabelText("modelSelector.enableFallback");

    view.rerender(
      <AgentModelSettings
        agentId="default"
        {...settingsProps}
        activeModelId="gpt-3.5-turbo"
      />,
    );
    await user.click(screen.getByRole("button", { name: /common.save/ }));

    await waitFor(() =>
      expect(agentsApi.updateModelSettings).toHaveBeenCalledOnce(),
    );
    const [, patch] = vi.mocked(agentsApi.updateModelSettings).mock.calls[0];
    expect(patch).not.toHaveProperty("active_model");
    expect(patch).not.toHaveProperty("channels");
  });

  it("preserves unavailable fallback and subagent slots when saving", async () => {
    vi.mocked(agentsApi.getAgent).mockResolvedValue({
      id: "default",
      name: "Default",
      fallback_models: [
        { provider_id: "removed-provider", model: "removed-model" },
      ],
      fallback_policy: { enabled: true, target_scope: "configured" },
      subagent_model: {
        provider_id: "removed-provider",
        model: "removed-subagent-model",
      },
      thinking_level: "inherit",
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(
      await screen.findByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );
    await screen.findByText("removed-provider:removed-model");
    await user.click(screen.getByRole("button", { name: /common.save/ }));

    await waitFor(() =>
      expect(agentsApi.updateModelSettings).toHaveBeenCalledOnce(),
    );
    expect(agentsApi.updateModelSettings).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        fallback_models: [
          { provider_id: "removed-provider", model: "removed-model" },
        ],
        subagent_model: {
          provider_id: "removed-provider",
          model: "removed-subagent-model",
        },
      }),
    );
  });

  it("ignores agent settings loaded for the previously selected agent", async () => {
    const oldAgentResponse =
      deferred<Awaited<ReturnType<typeof agentsApi.getAgent>>>();
    vi.mocked(agentsApi.getAgent).mockImplementation((agentId) =>
      agentId === "agent-b"
        ? Promise.resolve({
            id: "agent-b",
            name: "Agent B",
            fallback_models: [],
            fallback_policy: { enabled: false, target_scope: "configured" },
            subagent_model: null,
            thinking_level: "inherit",
          })
        : oldAgentResponse.promise,
    );
    const user = userEvent.setup();
    const settingsProps = {
      providers: [
        {
          id: mockProvider.id,
          name: mockProvider.name,
          models: mockProvider.models,
        },
      ],
      activeProviderId: "openai",
      activeModelId: "gpt-4",
    };
    const view = renderWithProviders(
      <AgentModelSettings agentId="default" {...settingsProps} />,
    );
    await user.click(
      screen.getByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );

    view.rerender(<AgentModelSettings agentId="agent-b" {...settingsProps} />);
    await user.click(
      screen.getByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );
    expect(
      await screen.findByLabelText("modelSelector.enableFallback"),
    ).not.toBeChecked();

    oldAgentResponse.resolve({
      id: "default",
      name: "Default",
      fallback_models: [],
      fallback_policy: { enabled: true, target_scope: "configured" },
      subagent_model: null,
      thinking_level: "inherit",
    });
    await waitFor(() => {
      expect(
        screen.getByLabelText("modelSelector.enableFallback"),
      ).not.toBeChecked();
    });
  });

  it("ignores agent settings saved for the previously selected agent", async () => {
    const oldSave =
      deferred<Awaited<ReturnType<typeof agentsApi.updateModelSettings>>>();
    vi.mocked(agentsApi.getAgent).mockImplementation((agentId) =>
      Promise.resolve({
        id: agentId,
        name: agentId,
        fallback_models: [],
        fallback_policy: {
          enabled: agentId === "default",
          target_scope: "configured",
        },
        subagent_model: null,
        thinking_level: "inherit",
      }),
    );
    vi.mocked(agentsApi.updateModelSettings).mockReturnValue(oldSave.promise);
    const user = userEvent.setup();
    const settingsProps = {
      providers: [
        {
          id: mockProvider.id,
          name: mockProvider.name,
          models: mockProvider.models,
        },
      ],
      activeProviderId: "openai",
      activeModelId: "gpt-4",
    };
    const view = renderWithProviders(
      <AgentModelSettings agentId="default" {...settingsProps} />,
    );
    await user.click(
      screen.getByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );
    await screen.findByLabelText("modelSelector.enableFallback");
    await user.click(screen.getByRole("button", { name: /common.save/ }));

    view.rerender(<AgentModelSettings agentId="agent-b" {...settingsProps} />);
    await user.click(
      screen.getByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );
    expect(
      await screen.findByLabelText("modelSelector.enableFallback"),
    ).not.toBeChecked();

    oldSave.resolve({
      id: "default",
      name: "Default",
      fallback_models: [],
      fallback_policy: { enabled: true, target_scope: "configured" },
      subagent_model: null,
      thinking_level: "inherit",
    });

    await waitFor(() => {
      expect(
        screen.getByLabelText("modelSelector.enableFallback"),
      ).not.toBeChecked();
    });
  });

  it("offers retry after agent settings fail to load", async () => {
    vi.mocked(agentsApi.getAgent)
      .mockRejectedValueOnce(new Error("load blocked"))
      .mockResolvedValueOnce({
        id: "default",
        name: "Default",
        fallback_models: [],
        fallback_policy: { enabled: true, target_scope: "configured" },
        subagent_model: null,
        thinking_level: "inherit",
      });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(
      screen.getByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("load blocked");
    await user.click(
      screen.getByRole("button", { name: "modelSelector.retry" }),
    );

    expect(
      await screen.findByLabelText("modelSelector.enableFallback"),
    ).toBeChecked();
  });

  it("disables thinking controls for unsupported active models", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(
      await screen.findByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );

    expect(
      await screen.findByRole("combobox", {
        name: "modelSelector.thinkingLevel",
      }),
    ).toBeDisabled();
    expect(
      screen.getByText("modelSelector.thinkingUnsupported"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /common.save/ }));
    await waitFor(() =>
      expect(agentsApi.updateModelSettings).toHaveBeenCalledOnce(),
    );
    expect(agentsApi.updateModelSettings).toHaveBeenCalledWith(
      "default",
      expect.not.objectContaining({ thinking_level: expect.anything() }),
    );
  });

  it("keeps thinking enabled for an unknown DashScope model", async () => {
    const dashscopeProvider = {
      ...mockProvider,
      id: "dashscope",
      name: "DashScope",
      chat_model: "DashScopeChatModel",
      models: [
        {
          ...mockProvider.models[0],
          id: "new-dashscope-model",
          name: "New DashScope Model",
          supports_agent_thinking: true,
        },
      ],
    };
    vi.mocked(providerApi.listProviders).mockResolvedValue([dashscopeProvider]);
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: {
        provider_id: "dashscope",
        model: "new-dashscope-model",
      },
    });
    vi.mocked(agentsApi.getAgent).mockResolvedValue({
      id: "default",
      name: "Default",
      fallback_models: [],
      fallback_policy: { enabled: true, target_scope: "configured" },
      subagent_model: null,
      thinking_level: "high",
    });
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("New DashScope Model");
    await user.click(screen.getAllByText("New DashScope Model")[0]);
    await user.click(
      await screen.findByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );

    expect(
      await screen.findByRole("combobox", {
        name: "modelSelector.thinkingLevel",
      }),
    ).not.toBeDisabled();
    await user.click(screen.getByRole("button", { name: /common.save/ }));

    await waitFor(() =>
      expect(agentsApi.updateModelSettings).toHaveBeenCalledOnce(),
    );
    expect(agentsApi.updateModelSettings).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({ thinking_level: "high" }),
    );
  });

  it("shows the actual fallback model reported by turn usage", async () => {
    useTurnUsageStore.getState().setSnapshot({
      usage: {
        provider_id: "openai",
        model_name: "gpt-3.5-turbo",
        total_tokens: 3,
      },
      context_usage: null,
    });

    renderWithProviders(<ModelSelector showAdvancedModelControls />);

    expect(
      await screen.findByText(
        (_, element) => element?.textContent === "GitBranchGPT-3.5 Turbo",
      ),
    ).toBeInTheDocument();
  });

  it("hides the fallback badge when actual usage matches the active model", async () => {
    useTurnUsageStore.getState().setSnapshot({
      usage: {
        provider_id: "openai",
        model_name: "gpt-4",
        total_tokens: 3,
      },
      context_usage: null,
    });

    renderWithProviders(<ModelSelector showAdvancedModelControls />);
    await screen.findAllByText("GPT-4");

    expect(
      screen.queryByLabelText("modelSelector.fallbackActive"),
    ).not.toBeInTheDocument();
  });

  it("safely shows unknown actual provider and model ids", async () => {
    useTurnUsageStore.getState().setSnapshot({
      usage: {
        provider_id: "unlisted-provider",
        model_name: "unlisted-model",
        total_tokens: 3,
      },
      context_usage: null,
    });

    renderWithProviders(<ModelSelector showAdvancedModelControls />);

    expect(await screen.findByText("unlisted-model")).toBeInTheDocument();
    expect(
      screen.getByLabelText("modelSelector.fallbackActive"),
    ).toBeInTheDocument();
  });
});
