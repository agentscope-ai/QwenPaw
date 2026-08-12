import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import ModelSelector from "./index";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    listProviders: vi.fn(),
    getActiveModels: vi.fn(),
    setActiveLlm: vi.fn(),
  },
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: vi.fn(() => ({ selectedAgent: "default" })),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

vi.mock("lucide-react", () => ({
  Loader2: () => "Loader2",
  ExternalLink: () => "ExternalLink",
  ChevronDown: () => "ChevronDown",
  ChevronRight: () => "ChevronRight",
  Search: () => "Search",
  X: () => "X",
  Check: () => "Check",
  AlertCircle: () => "AlertCircle",
  Eye: () => "Eye",
  Zap: () => "Zap",
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

import { providerApi } from "@/api/modules/provider";

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
    },
  ],
  extra_models: [],
};

const mockActiveModels = {
  active_llm: { provider_id: "openai", model: "gpt-4" },
};

function setupDefaultMocks() {
  vi.mocked(providerApi.listProviders).mockResolvedValue([mockProvider]);
  vi.mocked(providerApi.getActiveModels).mockResolvedValue(mockActiveModels);
}

function renderEstablishedSelector() {
  return renderWithProviders(
    <ModelSelector chatId="chat-1" sessionId="session-1" />,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ModelSelector", () => {
  beforeEach(() => {
    sessionStorage.clear();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("displays current active model name on trigger button after loading", async () => {
    renderWithProviders(<ModelSelector />);
    expect((await screen.findAllByText("GPT-4"))[0]).toBeInTheDocument();
  });

  it("displays i18n key when there is no active model", async () => {
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: undefined,
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

  it("clicking trigger button opens dropdown and shows provider list", async () => {
    const user = userEvent.setup();
    renderEstablishedSelector();
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);

    expect(await screen.findByText("OpenAI")).toBeInTheDocument();
  });

  it("stores a selection for the current session without changing the agent", async () => {
    const user = userEvent.setup();
    renderEstablishedSelector();
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    const gpt35 = await screen.findByText("GPT-3.5 Turbo");
    await user.click(gpt35);

    expect(
      JSON.parse(
        sessionStorage.getItem(
          "qwenpaw-session-model-override:default:session-1",
        ) || "null",
      ),
    ).toEqual({
      provider_id: "openai",
      model: "gpt-3.5-turbo",
    });
    expect(providerApi.setActiveLlm).not.toHaveBeenCalled();
  });

  it("publishes the selected model context window", async () => {
    const switched = vi.fn();
    window.addEventListener("model-switched", switched);
    const user = userEvent.setup();
    renderEstablishedSelector();
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    await user.click(await screen.findByText("GPT-3.5 Turbo"));

    await waitFor(() => expect(switched).toHaveBeenCalledOnce());
    const event = switched.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toEqual({
      maxInputLength: 16384,
    });
    window.removeEventListener("model-switched", switched);
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
    renderEstablishedSelector();
    await screen.findAllByText("GPT-4");

    await user.click(screen.getAllByText("GPT-4")[0]);
    const gpt4Items = await screen.findAllByText("GPT-4");
    await user.click(gpt4Items[gpt4Items.length - 1]);

    expect(providerApi.setActiveLlm).not.toHaveBeenCalled();
  });

  it("dropdown shows empty state when no providers are available", async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([]);
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: undefined,
    });
    const user = userEvent.setup();
    renderEstablishedSelector();
    await screen.findAllByText("modelSelector.selectModel");

    await user.click(screen.getAllByText("modelSelector.selectModel")[0]);

    expect(
      await screen.findByText("modelSelector.noConfiguredModels"),
    ).toBeInTheDocument();
  });

  it("restores a pending selection when the component loads", async () => {
    sessionStorage.setItem(
      "qwenpaw-session-model-override:default:session-1",
      JSON.stringify({
        provider_id: "openai",
        model: "gpt-3.5-turbo",
      }),
    );
    renderEstablishedSelector();
    expect(
      (await screen.findAllByText("GPT-3.5 Turbo"))[0],
    ).toBeInTheDocument();
  });

  it("does not open model selection before the first message", async () => {
    sessionStorage.setItem(
      "qwenpaw-session-model-override:default:new",
      JSON.stringify({ provider_id: "openai", model: "gpt-3.5-turbo" }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ModelSelector />);
    const triggerName = (await screen.findAllByText("GPT-4"))[0];

    await user.click(triggerName);

    expect(screen.queryByText("OpenAI")).not.toBeInTheDocument();
    expect(triggerName.closest("[aria-disabled='true']")).toBeInTheDocument();
    expect(sessionStorage.length).toBe(0);
  });

  it("enables model selection when the first message resolves the chat", async () => {
    const user = userEvent.setup();
    const view = renderWithProviders(<ModelSelector />);
    const disabledTrigger = (await screen.findAllByText("GPT-4"))[0];

    expect(
      disabledTrigger.closest("[aria-disabled='true']"),
    ).toBeInTheDocument();

    view.rerender(<ModelSelector chatId="chat-1" sessionId="session-1" />);
    const enabledTrigger = (await screen.findAllByText("GPT-4"))[0];
    await user.click(enabledTrigger);

    expect(await screen.findByText("OpenAI")).toBeInTheDocument();
  });

  it("refreshes the displayed model after a model command completes", async () => {
    renderEstablishedSelector();
    await screen.findAllByText("GPT-4");
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({
      active_llm: { provider_id: "openai", model: "gpt-3.5-turbo" },
    });

    act(() => {
      window.dispatchEvent(
        new CustomEvent("session-model-command-completed", {
          detail: { agentId: "default" },
        }),
      );
    });

    expect(
      (await screen.findAllByText("GPT-3.5 Turbo"))[0],
    ).toBeInTheDocument();
    expect(providerApi.getActiveModels).toHaveBeenLastCalledWith({
      scope: "effective",
      agent_id: "default",
      chat_id: "chat-1",
    });
  });
});
