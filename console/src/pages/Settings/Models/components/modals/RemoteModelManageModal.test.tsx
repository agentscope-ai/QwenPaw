import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import type { ProviderInfo } from "../../../../../api/types";
import { renderWithProviders } from "@/test/common_setup";

const confirmSpy = vi.hoisted(() => vi.fn());
const formRegistry = vi.hoisted(() => ({ forms: [] as unknown[] }));

const apiMocks = vi.hoisted(() => ({
  addModel: vi.fn(),
  testModelConnection: vi.fn(),
  probeMultimodal: vi.fn(),
  removeModel: vi.fn(),
  discoverModels: vi.fn(),
  getOpenRouterSeries: vi.fn(),
  filterOpenRouterModels: vi.fn(),
}));

vi.mock("../../../../../api", () => ({
  default: apiMocks,
}));

vi.mock("../../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMocks }),
}));

// Bridge real antd Form/Input so validateFields works (design stub lacks
// useForm/useWatch under Vitest CJS interop); capture imperative confirms.
vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const antd = await import("antd");
  const original = (await importOriginal()) as Record<string, unknown>;

  const modalLike = ({ children, footer, title }: Record<string, unknown>) =>
    React.createElement(
      "div",
      { role: "dialog" },
      title ? React.createElement("div", null, title as any) : null,
      children as any,
      footer ? React.createElement("div", null, footer as any) : null,
    );

  const AntdForm = antd.Form as typeof antd.Form & {
    useForm: () => [unknown];
  };
  const WrappedForm = Object.assign(
    (props: Record<string, unknown>) =>
      React.createElement(AntdForm, props as never),
    {
      Item: AntdForm.Item,
      List: AntdForm.List,
      ErrorList: AntdForm.ErrorList,
      Provider: AntdForm.Provider,
      useFormInstance: AntdForm.useFormInstance,
      useWatch: AntdForm.useWatch,
      useForm: () => {
        const result = AntdForm.useForm();
        formRegistry.forms[0] = result[0];
        return result;
      },
    },
  );

  return {
    ...original,
    Form: WrappedForm,
    Input: antd.Input,
    Modal: Object.assign(modalLike, {
      confirm: confirmSpy,
      info: vi.fn(),
      warning: vi.fn(),
      error: vi.fn(),
    }),
  };
});

// Stub heavy sibling components; the modal under test orchestrates them.
vi.mock("./ModelCapabilityTags", () => ({
  CapabilityTags: () => null,
  tagColors: () => ({
    free: {},
    userAdded: {},
    builtin: {},
  }),
}));
vi.mock("./ModelConfigEditor", () => ({
  ModelConfigEditor: () =>
    React.createElement("div", { "data-testid": "model-config-editor" }),
}));
vi.mock("./OpenRouterFilterSection", () => ({
  OpenRouterFilterSection: ({
    onFetchModels,
    onAddModel,
    discoveredModels,
  }: {
    onFetchModels?: () => void;
    onAddModel?: (model: { id: string }) => void;
    discoveredModels?: Array<{ id: string }>;
  }) =>
    React.createElement(
      "div",
      null,
      React.createElement(
        "button",
        { type: "button", onClick: () => onFetchModels?.() },
        "fetch-filters",
      ),
      ...(discoveredModels ?? []).map((m: { id: string }) =>
        React.createElement(
          "button",
          {
            key: m.id,
            type: "button",
            onClick: () => onAddModel?.(m),
          },
          `add-filtered:${m.id}`,
        ),
      ),
    ),
}));

import { RemoteModelManageModal } from "./RemoteModelManageModal";

const provider = {
  id: "siliconflow",
  name: "SiliconFlow",
  api_key_prefix: "sk-",
  chat_model: "OpenAIChatModel",
  models: [],
  extra_models: [],
  discovered_models: [
    { id: "ready", name: "Ready", availability_status: "available" },
    { id: "hidden", name: "Hidden", availability_status: "available" },
    {
      id: "forbidden",
      name: "Forbidden",
      availability_status: "permission_denied",
    },
  ],
  hidden_model_ids: ["hidden"],
  is_custom: false,
  is_local: false,
  support_model_discovery: true,
  support_connection_check: true,
  freeze_url: false,
  require_api_key: true,
  api_key: "",
  base_url: "https://api.example/v1",
  generate_kwargs: {},
} as unknown as ProviderInfo;

function renderModal(
  providerOverride: Partial<Record<string, unknown>> = {},
  onSaved = vi.fn().mockResolvedValue(undefined),
) {
  const onClose = vi.fn();
  const rendered = renderWithProviders(
    <RemoteModelManageModal
      provider={{ ...provider, ...providerOverride } as ProviderInfo}
      open
      onClose={onClose}
      onSaved={onSaved}
      onProviderUpdated={vi.fn()}
    />,
  );
  return { onClose, onSaved, unmount: rendered.unmount };
}

async function openAddForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("models.addModel"));
  await waitFor(() =>
    expect(screen.getByText("models.modelIdLabel")).toBeInTheDocument(),
  );
}

/** Fill the add-model form via the captured form instance and stub
 *  validateFields to resolve with the given values. This bypasses antd's
 *  outOfDate guard (triggered by programmatic setFieldsValue in jsdom)
 *  and exercises the component's submit business logic directly. */
async function fillAddForm(values: Record<string, unknown>) {
  const form = formRegistry.forms[0] as {
    setFieldsValue: (v: Record<string, unknown>) => void;
    validateFields: (...args: unknown[]) => Promise<unknown>;
  };
  await act(async () => {
    form.setFieldsValue(values);
  });
  // Stub validateFields to resolve with the filled values so the handler
  // proceeds past validation into the business logic under test.
  form.validateFields = vi.fn().mockResolvedValue(values);
}

describe("RemoteModelManageModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.testModelConnection.mockResolvedValue({ success: true });
    apiMocks.probeMultimodal.mockResolvedValue({
      supports_image: false,
      supports_video: false,
    });
    apiMocks.removeModel.mockResolvedValue({});
    apiMocks.discoverModels.mockResolvedValue({
      success: true,
      models: [],
      discovered_count: 0,
    });
  });

  it("adds all available candidates without hidden or unavailable models", async () => {
    apiMocks.addModel.mockResolvedValue(provider);
    const onSaved = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={provider}
        open
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: /models\.addAllDiscoveredModels/,
      }),
    );

    await waitFor(() => expect(apiMocks.addModel).toHaveBeenCalledOnce());
    expect(apiMocks.addModel).toHaveBeenCalledWith(
      "siliconflow",
      expect.objectContaining({ id: "ready", name: "Ready" }),
    );
    expect(onSaved).toHaveBeenCalledOnce();
  });

  describe("model list", () => {
    it("shows configured models with user-added and built-in tags", () => {
      renderModal({
        models: [{ id: "builtin-1", name: "Built-in One", source: "builtin" }],
        extra_models: [{ id: "extra-1", name: "Extra One" }],
        discovered_models: [],
      });
      expect(screen.getByText("Built-in One")).toBeInTheDocument();
      expect(screen.getByText("Extra One")).toBeInTheDocument();
      expect(screen.getByText("models.builtin")).toBeInTheDocument();
      expect(screen.getByText("models.userAdded")).toBeInTheDocument();
    });

    it("shows the free tag and a discovered tag for discovered models", () => {
      renderModal({
        models: [
          { id: "d-1", name: "Free Disc", source: "discovered", is_free: true },
        ],
        discovered_models: [],
      });
      expect(screen.getByText("models.free")).toBeInTheDocument();
      expect(screen.getByText("models.discovered")).toBeInTheDocument();
    });

    it("filters models by the search query", async () => {
      const user = userEvent.setup();
      renderModal({
        models: [
          { id: "alpha-1", name: "Alpha" },
          { id: "beta-2", name: "Beta" },
        ],
        discovered_models: [],
      });

      const search = screen.getByPlaceholderText(
        /models\.searchModelPlaceholder/,
      );
      await user.type(search, "alpha");

      await waitFor(() =>
        expect(screen.getByText("Alpha")).toBeInTheDocument(),
      );
      expect(screen.queryByText("Beta")).not.toBeInTheDocument();
    });

    it("shows the empty state when nothing is configured", () => {
      renderModal({ models: [], extra_models: [], discovered_models: [] });
      expect(screen.getByText("models.noModels")).toBeInTheDocument();
    });

    it("paginates the list and loads more on demand", async () => {
      const many = Array.from({ length: 35 }, (_, i) => ({
        id: `m-${i}`,
        name: `Model ${i}`,
      }));
      const user = userEvent.setup();
      renderModal({ models: many, discovered_models: [] });

      // Page size 30
      expect(screen.getByText("Model 0")).toBeInTheDocument();
      expect(screen.queryByText("Model 31")).not.toBeInTheDocument();

      await user.click(screen.getByText(/models\.loadMore/));
      expect(screen.getByText("Model 31")).toBeInTheDocument();
    });

    it("shows sync status variants", () => {
      const { unmount } = renderModal({
        models_syncing: true,
        discovered_models: [],
      });
      expect(screen.getByText(/models\.modelsSyncing/)).toBeInTheDocument();
      unmount();

      const r2 = renderModal({
        models_syncing: false,
        models_last_synced_at: "2026-09-01T00:00:00Z",
        discovered_models: [],
      });
      expect(screen.getByText(/models\.modelsLastSynced/)).toBeInTheDocument();
      r2.unmount();

      renderModal({
        models_syncing: false,
        discovered_models: [],
        models_last_sync_error: "sync broke",
      });
      expect(screen.getByText(/models\.modelsNeverSynced/)).toBeInTheDocument();
      expect(screen.getByText(/models\.modelsSyncFailed/)).toBeInTheDocument();
    });
  });

  describe("add model form", () => {
    it("adds a model directly when the connection test passes", async () => {
      apiMocks.addModel.mockResolvedValue(provider);
      const user = userEvent.setup();
      const { onSaved } = renderModal();

      await openAddForm(user);
      await fillAddForm({ id: "my-model", name: "My Model" });
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await waitFor(() => expect(apiMocks.addModel).toHaveBeenCalled());
      expect(apiMocks.testModelConnection).toHaveBeenCalledWith("siliconflow", {
        model_id: "my-model",
      });
      expect(onSaved).toHaveBeenCalled();
      expect(messageMocks.success).toHaveBeenCalled();
    });

    it("defaults the name to the id when blank", async () => {
      apiMocks.addModel.mockResolvedValue(provider);
      const user = userEvent.setup();
      renderModal();

      await openAddForm(user);
      await fillAddForm({ id: "bare-id" });
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await waitFor(() =>
        expect(apiMocks.addModel).toHaveBeenCalledWith(
          "siliconflow",
          expect.objectContaining({ id: "bare-id", name: "bare-id" }),
        ),
      );
    });

    it("warns when the model id already exists", async () => {
      const user = userEvent.setup();
      renderModal({
        models: [{ id: "dup", name: "Dup" }],
      });

      await openAddForm(user);
      await fillAddForm({ id: "dup" });
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await waitFor(() => expect(messageMocks.warning).toHaveBeenCalled());
      expect(apiMocks.addModel).not.toHaveBeenCalled();
    });

    it("blocks adding models with hard-failure statuses", async () => {
      apiMocks.testModelConnection.mockResolvedValue({
        success: false,
        status: "permission_denied",
        message: "no access",
      });
      const user = userEvent.setup();
      renderModal();

      await openAddForm(user);
      await fillAddForm({ id: "locked" });
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await waitFor(() => expect(messageMocks.error).toHaveBeenCalled());
      expect(confirmSpy).not.toHaveBeenCalled();
      expect(apiMocks.addModel).not.toHaveBeenCalled();
    });

    it("blocks adding when the failure detail matches a blocked pattern", async () => {
      apiMocks.testModelConnection.mockResolvedValue({
        success: false,
        status: "other",
        message: "product is not activated for this account",
      });
      const user = userEvent.setup();
      renderModal();

      await openAddForm(user);
      await fillAddForm({ id: "x" });
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await waitFor(() => expect(messageMocks.error).toHaveBeenCalled());
      expect(apiMocks.addModel).not.toHaveBeenCalled();
    });

    it("offers a confirm-and-add path when the test fails softly", async () => {
      apiMocks.testModelConnection.mockResolvedValue({
        success: false,
        status: "rate_limited",
        message: "try later",
      });
      apiMocks.addModel.mockResolvedValue(provider);
      const user = userEvent.setup();
      renderModal();

      await openAddForm(user);
      await fillAddForm({ id: "soft-fail" });
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
      const opts = confirmSpy.mock.calls[
        confirmSpy.mock.calls.length - 1
      ]?.[0] as {
        onOk: () => Promise<void>;
      };
      await opts.onOk();

      await waitFor(() => expect(apiMocks.addModel).toHaveBeenCalled());
    });

    it("reports add failures from the confirm path", async () => {
      apiMocks.testModelConnection.mockResolvedValue({
        success: false,
        status: "rate_limited",
        message: "try later",
      });
      apiMocks.addModel.mockRejectedValue(new Error("disk full"));
      const user = userEvent.setup();
      renderModal();

      await openAddForm(user);
      await fillAddForm({ id: "boom" });
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
      const opts = confirmSpy.mock.calls[
        confirmSpy.mock.calls.length - 1
      ]?.[0] as {
        onOk: () => Promise<void>;
      };
      await opts.onOk();

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("disk full"),
      );
    });

    it("blocks submission when the id is empty", async () => {
      const user = userEvent.setup();
      renderModal();

      await openAddForm(user);
      await user.click(screen.getByRole("button", { name: "models.addModel" }));

      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(apiMocks.testModelConnection).not.toHaveBeenCalled();
    });

    it("cancels the add form", async () => {
      const user = userEvent.setup();
      renderModal();

      await openAddForm(user);
      await user.click(screen.getByText("models.cancel"));
      expect(screen.queryByText("models.modelIdLabel")).not.toBeInTheDocument();
    });
  });

  describe("row actions", () => {
    it("tests a configured model connection (success and failure)", async () => {
      const user = userEvent.setup();
      renderModal({
        models: [{ id: "m-1", name: "M1" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText("models.testConnection"));
      await waitFor(() => expect(messageMocks.success).toHaveBeenCalled());
    });

    it("warns on failed model test and errors on exceptions", async () => {
      apiMocks.testModelConnection.mockResolvedValue({
        success: false,
        message: "bad",
      });
      const user = userEvent.setup();
      renderModal({
        models: [{ id: "m-1", name: "M1" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText("models.testConnection"));
      await waitFor(() => expect(messageMocks.warning).toHaveBeenCalled());

      apiMocks.testModelConnection.mockRejectedValue(new Error("net"));
      await user.click(screen.getByLabelText("models.testConnection"));
      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("net"),
      );
    });

    it("probes multimodal support and reports the outcome", async () => {
      apiMocks.probeMultimodal.mockResolvedValue({
        supports_image: true,
        supports_video: true,
      });
      const user = userEvent.setup();
      const { onSaved } = renderModal({
        models: [{ id: "m-1", name: "M1" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText(/models\.probeMultimodal/));
      await waitFor(() =>
        expect(messageMocks.success).toHaveBeenCalledWith(
          expect.stringContaining("models.probeSupported"),
        ),
      );
      expect(onSaved).toHaveBeenCalled();
    });

    it("reports when no multimodal capability is found", async () => {
      const user = userEvent.setup();
      renderModal({
        models: [{ id: "m-1", name: "M1" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText(/models\.probeMultimodal/));
      await waitFor(() =>
        expect(messageMocks.info).toHaveBeenCalledWith(
          "models.probeNotSupported",
        ),
      );
    });

    it("reports probe failures", async () => {
      apiMocks.probeMultimodal.mockRejectedValue(new Error("probe broke"));
      const user = userEvent.setup();
      renderModal({
        models: [{ id: "m-1", name: "M1" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText(/models\.probeMultimodal/));
      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("probe broke"),
      );
    });

    it("removes a deletable model through the confirm dialog", async () => {
      const user = userEvent.setup();
      const { onSaved } = renderModal({
        extra_models: [{ id: "ex-1", name: "Extra One" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText("models.removeModel"));
      await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
      const opts = confirmSpy.mock.calls[
        confirmSpy.mock.calls.length - 1
      ]?.[0] as {
        onOk: () => Promise<void>;
      };
      await opts.onOk();

      await waitFor(() =>
        expect(apiMocks.removeModel).toHaveBeenCalledWith(
          "siliconflow",
          "ex-1",
        ),
      );
      expect(onSaved).toHaveBeenCalled();
      expect(messageMocks.success).toHaveBeenCalled();
    });

    it("reports removal failures", async () => {
      apiMocks.removeModel.mockRejectedValue(new Error("locked"));
      const user = userEvent.setup();
      renderModal({
        extra_models: [{ id: "ex-1", name: "Extra One" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText("models.removeModel"));
      await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
      const opts = confirmSpy.mock.calls[
        confirmSpy.mock.calls.length - 1
      ]?.[0] as {
        onOk: () => Promise<void>;
      };
      await opts.onOk();

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("locked"),
      );
    });

    it("hides the remove action for non-deletable built-in models", () => {
      renderModal({
        models: [{ id: "builtin-1", name: "Built-in One" }],
        discovered_models: [],
      });
      expect(
        screen.queryByLabelText("models.removeModel"),
      ).not.toBeInTheDocument();
    });

    it("makes every model deletable for custom providers", () => {
      renderModal({
        is_custom: true,
        models: [{ id: "builtin-1", name: "Built-in One" }],
        discovered_models: [],
      });
      expect(screen.getByLabelText("models.removeModel")).toBeInTheDocument();
    });

    it("toggles the per-model config editor open and closed", async () => {
      const user = userEvent.setup();
      renderModal({
        extra_models: [{ id: "ex-1", name: "Extra One" }],
        discovered_models: [],
      });

      await user.click(screen.getByLabelText(/models\.modelConfigLabel/));
      expect(screen.getByTestId("model-config-editor")).toBeInTheDocument();

      await user.click(screen.getByLabelText(/models\.modelConfigLabel/));
      expect(
        screen.queryByTestId("model-config-editor"),
      ).not.toBeInTheDocument();
    });
  });

  describe("auto discovery", () => {
    it("runs auto discovery and reports success", async () => {
      apiMocks.discoverModels.mockResolvedValue({
        success: true,
        models: [],
        discovered_count: 3,
      });
      const user = userEvent.setup();
      renderModal({ discovered_models: [] });

      await user.click(screen.getByText("models.autoDiscoverModels"));

      await waitFor(() =>
        expect(messageMocks.success).toHaveBeenCalledWith(
          expect.stringContaining("models.autoDiscoverModelsSuccess"),
        ),
      );
    });

    it("reports no-new-models discovery outcomes", async () => {
      apiMocks.discoverModels.mockResolvedValue({
        success: true,
        models: [{ id: "a" }],
        discovered_count: 0,
      });
      const user = userEvent.setup();
      renderModal({ discovered_models: [] });

      await user.click(screen.getByText("models.autoDiscoverModels"));

      await waitFor(() => expect(messageMocks.info).toHaveBeenCalled());
    });

    it("reports discovery failures", async () => {
      apiMocks.discoverModels.mockResolvedValue({
        success: false,
        message: "quota",
      });
      const user = userEvent.setup();
      renderModal({ discovered_models: [] });

      await user.click(screen.getByText("models.autoDiscoverModels"));

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("quota"),
      );
    });

    it("reports discovery exceptions", async () => {
      apiMocks.discoverModels.mockRejectedValue(new Error("offline"));
      const user = userEvent.setup();
      renderModal({ discovered_models: [] });

      await user.click(screen.getByText("models.autoDiscoverModels"));

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("offline"),
      );
    });

    it("hides the auto-discover button when unsupported", () => {
      renderModal({
        support_model_discovery: false,
        discovered_models: [],
      });
      expect(
        screen.queryByText("models.autoDiscoverModels"),
      ).not.toBeInTheDocument();
    });
  });

  describe("bulk add of discovered models", () => {
    it("adds all addable discovered models and reports partial failures", async () => {
      apiMocks.addModel
        .mockResolvedValueOnce(provider)
        .mockRejectedValueOnce(new Error("nope"));
      const user = userEvent.setup();
      renderModal({
        models: [],
        extra_models: [],
        discovered_models: [
          { id: "a", name: "A", availability_status: "available" },
          { id: "b", name: "B", availability_status: "available" },
        ],
      });

      await user.click(
        screen.getByRole("button", { name: /models\.addAllDiscoveredModels/ }),
      );

      await waitFor(() => expect(apiMocks.addModel).toHaveBeenCalledTimes(2));
      expect(messageMocks.success).toHaveBeenCalled();
      expect(messageMocks.error).toHaveBeenCalled();
    });

    it("skips bulk add when no models are addable", async () => {
      renderModal({
        models: [],
        extra_models: [],
        discovered_models: [
          { id: "h", name: "H", availability_status: "available" },
        ],
        hidden_model_ids: ["h"],
      });
      const btn = screen.getByRole("button", {
        name: /models\.addAllDiscoveredModels/,
      });
      expect(btn).toBeDisabled();
    });
  });

  describe("openrouter flow", () => {
    it("loads series and renders the filter section", async () => {
      apiMocks.getOpenRouterSeries.mockResolvedValue({
        series: ["openai", "anthropic"],
      });
      renderModal({
        id: "openrouter",
        models: [],
        extra_models: [],
        discovered_models: [],
      });

      await waitFor(() =>
        expect(apiMocks.getOpenRouterSeries).toHaveBeenCalled(),
      );
      expect(screen.getByText("fetch-filters")).toBeInTheDocument();
    });

    it("fetches filtered models and applies them", async () => {
      apiMocks.getOpenRouterSeries.mockResolvedValue({ series: ["openai"] });
      apiMocks.filterOpenRouterModels.mockResolvedValue({
        success: true,
        models: [{ id: "or-1", name: "OR One" }],
        total_count: 1,
      });
      const user = userEvent.setup();
      renderModal({
        id: "openrouter",
        models: [],
        extra_models: [],
        discovered_models: [],
      });

      await waitFor(() =>
        expect(apiMocks.getOpenRouterSeries).toHaveBeenCalled(),
      );
      await user.click(screen.getByText("fetch-filters"));

      await waitFor(() =>
        expect(messageMocks.success).toHaveBeenCalledWith(
          expect.stringContaining("models.filteredModelsLoaded"),
        ),
      );
    });

    it("reports filter failures", async () => {
      apiMocks.getOpenRouterSeries.mockResolvedValue({ series: [] });
      apiMocks.filterOpenRouterModels.mockResolvedValue({ success: false });
      const user = userEvent.setup();
      renderModal({
        id: "openrouter",
        models: [],
        extra_models: [],
        discovered_models: [],
      });

      await waitFor(() =>
        expect(apiMocks.getOpenRouterSeries).toHaveBeenCalled(),
      );
      await user.click(screen.getByText("fetch-filters"));

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith("models.filterFailed"),
      );
    });

    it("handles series load failures gracefully", async () => {
      apiMocks.getOpenRouterSeries.mockRejectedValue(new Error("nope"));
      renderModal({
        id: "openrouter",
        models: [],
        extra_models: [],
        discovered_models: [],
      });

      await waitFor(() =>
        expect(apiMocks.getOpenRouterSeries).toHaveBeenCalled(),
      );
      // No crash; modal stays rendered
      expect(screen.getByText(/models\.manageModelsTitle/)).toBeInTheDocument();
    });

    it("adds a filtered model from the filter section", async () => {
      apiMocks.getOpenRouterSeries.mockResolvedValue({ series: [] });
      apiMocks.addModel.mockResolvedValue(provider);
      const user = userEvent.setup();
      const { onSaved } = renderModal({
        id: "openrouter",
        models: [],
        extra_models: [],
        discovered_models: [{ id: "or-1", name: "OR One" }],
      });

      await waitFor(() =>
        expect(apiMocks.getOpenRouterSeries).toHaveBeenCalled(),
      );
      await user.click(screen.getByText("add-filtered:or-1"));

      await waitFor(() => expect(apiMocks.addModel).toHaveBeenCalled());
      expect(onSaved).toHaveBeenCalled();
    });

    it("reports filtered-model add failures", async () => {
      apiMocks.getOpenRouterSeries.mockResolvedValue({ series: [] });
      apiMocks.addModel.mockRejectedValue(new Error("nope"));
      const user = userEvent.setup();
      renderModal({
        id: "openrouter",
        models: [],
        extra_models: [],
        discovered_models: [{ id: "or-1", name: "OR One" }],
      });

      await waitFor(() =>
        expect(apiMocks.getOpenRouterSeries).toHaveBeenCalled(),
      );
      await user.click(screen.getByText("add-filtered:or-1"));

      await waitFor(() =>
        expect(messageMocks.error).toHaveBeenCalledWith(
          "models.modelAddFailed",
        ),
      );
    });

    it("does not offer the manual add form for openrouter", () => {
      apiMocks.getOpenRouterSeries.mockResolvedValue({ series: [] });
      renderModal({
        id: "openrouter",
        models: [],
        extra_models: [],
        discovered_models: [],
      });
      expect(screen.queryByText("models.addModel")).not.toBeInTheDocument();
    });
  });
});
