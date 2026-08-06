import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ModelSelector from "./index";
import { AgentModelSettings } from "./AgentModelSettings";
import { useTurnUsageStore } from "../turnUsageStore";

const agentStoreState = vi.hoisted(() => ({ selectedAgent: "default" }));

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

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
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
  Pin: () => "Pin",
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
  vi.mocked(agentsApi.updateAgent).mockImplementation(async (_id, config) =>
    Promise.resolve(config),
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
    useTurnUsageStore.getState().reset();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("displays current active model name on trigger button after loading", async () => {
    renderWithProviders(<ModelSelector />);
    expect((await screen.findAllByText("GPT-4"))[0]).toBeInTheDocument();
  });

  it("shows agent model routing at the bottom of the model list", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);

    const routingToggle = await screen.findByRole("button", {
      name: /modelSelector.agentModelSettings/,
    });
    const searchInput = screen.getByPlaceholderText(
      "modelSelector.searchModels",
    );
    const proTab = screen.getByRole("tab", { name: "PRO" });
    const showAllButton = screen.getByRole("button", {
      name: "modelSelector.showAll",
    });

    expect(
      routingToggle.compareDocumentPosition(searchInput) &
        Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy();
    expect(
      routingToggle.compareDocumentPosition(proTab) &
        Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy();
    expect(
      routingToggle.compareDocumentPosition(showAllButton) &
        Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy();
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

  it("shows only explicitly recommended models by default", async () => {
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

    expect(await screen.findByText("Model 4")).toBeInTheDocument();
    expect(screen.getByText("Model 6")).toBeInTheDocument();
    expect(screen.queryByText("Model 1")).not.toBeInTheDocument();
  });

  it("keeps the active model visible when no models are recommended", async () => {
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
    expect(screen.queryByText("GPT-3.5 Turbo")).not.toBeInTheDocument();
  });

  it("keeps pinned models visible without recommending other added models", async () => {
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

    expect(await screen.findByText("GPT-3.5 Turbo")).toBeInTheDocument();
    expect(screen.queryByText("Added Model")).not.toBeInTheDocument();
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
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
          { ...mockProvider.models[0], thinking_enabled: true },
          mockProvider.models[1],
        ],
      },
    ]);
    vi.mocked(agentsApi.updateAgent).mockImplementation(
      async (_agentId, config) => ({
        ...config,
        description: "preserved by backend merge",
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(
      await screen.findByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );

    await user.selectOptions(
      await screen.findByLabelText("modelSelector.thinkingLevel"),
      "high",
    );
    await user.selectOptions(
      screen.getByLabelText("modelSelector.subagentModel"),
      "openai:gpt-3.5-turbo",
    );
    await user.selectOptions(
      screen.getByLabelText("modelSelector.chooseFallback"),
      "openai:gpt-3.5-turbo",
    );
    await user.click(
      screen.getByRole("button", { name: "modelSelector.addFallback" }),
    );
    await user.click(screen.getByRole("button", { name: /common.save/ }));

    await waitFor(() => expect(agentsApi.updateAgent).toHaveBeenCalledOnce());
    expect(agentsApi.updateAgent).toHaveBeenCalledWith(
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
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(
      await screen.findByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );
    await screen.findByText("removed-provider:removed-model");
    await user.click(screen.getByRole("button", { name: /common.save/ }));

    await waitFor(() => expect(agentsApi.updateAgent).toHaveBeenCalledOnce());
    expect(agentsApi.updateAgent).toHaveBeenCalledWith(
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
          chatModel: mockProvider.chat_model,
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
      deferred<Awaited<ReturnType<typeof agentsApi.updateAgent>>>();
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
    vi.mocked(agentsApi.updateAgent).mockReturnValue(oldSave.promise);
    const user = userEvent.setup();
    const settingsProps = {
      providers: [
        {
          id: mockProvider.id,
          name: mockProvider.name,
          chatModel: mockProvider.chat_model,
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
    renderWithProviders(<ModelSelector />);
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
    renderWithProviders(<ModelSelector />);
    await screen.findAllByText("GPT-4");
    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(
      await screen.findByRole("button", {
        name: /modelSelector.agentModelSettings/,
      }),
    );

    expect(
      await screen.findByLabelText("modelSelector.thinkingLevel"),
    ).toBeDisabled();
    expect(
      screen.getByText("modelSelector.thinkingUnsupported"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /common.save/ }));
    await waitFor(() => expect(agentsApi.updateAgent).toHaveBeenCalledOnce());
    expect(agentsApi.updateAgent).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({ thinking_level: "inherit" }),
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

    renderWithProviders(<ModelSelector />);

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

    renderWithProviders(<ModelSelector />);
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

    renderWithProviders(<ModelSelector />);

    expect(await screen.findByText("unlisted-model")).toBeInTheDocument();
    expect(
      screen.getByLabelText("modelSelector.fallbackActive"),
    ).toBeInTheDocument();
  });
});
