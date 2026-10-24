import type { ReactNode } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import type { ProviderInfo, ModelInfo } from "../../../../../api/types";
import { RemoteModelManageModal } from "./RemoteModelManageModal";
const api = vi.hoisted(() => ({
  getModelPool: vi.fn(),
  updateModelPool: vi.fn(),
  selectAllModels: vi.fn(),
  discoverModels: vi.fn(),
  addModel: vi.fn(),
  removeModel: vi.fn(),
  testModelConnection: vi.fn(),
  probeMultimodal: vi.fn(),
  listModelTemplates: vi.fn(),
  previewModelInfo: vi.fn(),
}));
const message = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
}));
vi.mock("../../../../../api", () => ({ default: api }));
vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message }),
}));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});
vi.mock("./ModelCapabilityTags", () => ({
  CapabilityTags: () => null,
  BillingTag: () => null,
}));
vi.mock("./ModelInfoPreview", () => ({
  ModelInfoPreview: () => <div>preview</div>,
}));
vi.mock("./ModelConfigEditor", () => ({
  ModelConfigEditor: () => <div>configuration</div>,
}));
vi.mock("@agentscope-ai/design", async (original) => {
  const actual = (await original()) as Record<string, unknown>;
  const antd = await import("antd");
  return {
    ...actual,
    Form: antd.Form,
    Input: antd.Input,
    Modal: ({
      open,
      children,
      title,
      onOk,
      onCancel,
      confirmLoading,
      cancelButtonProps,
    }: {
      open: boolean;
      children: ReactNode;
      title: ReactNode;
      onOk?: () => void;
      onCancel?: () => void;
      confirmLoading?: boolean;
      cancelButtonProps?: { disabled?: boolean };
    }) =>
      open ? (
        <div role="dialog">
          <h2>{title}</h2>
          {children}
          {onOk && (
            <button disabled={confirmLoading} onClick={onOk}>
              confirm
            </button>
          )}
          {onCancel && (
            <button disabled={cancelButtonProps?.disabled} onClick={onCancel}>
              cancel
            </button>
          )}
        </div>
      ) : null,
  };
});
const candidate = {
  id: "vendor/free",
  name: "New candidate",
  billing: "free",
  supports_image: true,
  effective_max_input_length: 1000000,
  max_output_length: 32000,
} as ModelInfo;
const chosen = {
  id: "chosen",
  name: "Chosen model",
  source: "user",
  billing: "paid",
} as ModelInfo;
const provider = {
  id: "openrouter",
  name: "OpenRouter",
  support_model_discovery: true,
  models: [],
  extra_models: [chosen],
  discovered_models: [candidate],
  seen_model_ids: [],
} as unknown as ProviderInfo;
async function render(providerOverride: Partial<ProviderInfo> = {}) {
  const onSaved = vi.fn();
  const onProviderUpdated = vi.fn();
  renderWithProviders(
    <RemoteModelManageModal
      provider={{ ...provider, ...providerOverride }}
      open
      onClose={vi.fn()}
      onSaved={onSaved}
      onProviderUpdated={onProviderUpdated}
    />,
  );
  await waitFor(() => expect(api.getModelPool).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.queryByText("common.loading")).not.toBeInTheDocument(),
  );
  return { onSaved, onProviderUpdated };
}
let serverProvider = provider;
beforeEach(() => {
  vi.clearAllMocks();
  serverProvider = provider;
  api.getModelPool.mockImplementation((_id, query) => {
    const selected = new Set(
      [...serverProvider.models, ...serverProvider.extra_models].map(
        (model) => model.id,
      ),
    );
    const pool = [
      ...new Map(
        [
          ...(serverProvider.discovered_models ?? []),
          ...serverProvider.models,
          ...serverProvider.extra_models,
        ].map((model) => [model.id, model]),
      ).values(),
    ];
    const filtered = pool.filter(
      (model) =>
        (query.tab === "all" ||
          selected.has(model.id) === (query.tab === "selected")) &&
        `${model.name} ${model.id}`
          .toLowerCase()
          .includes(query.search.toLowerCase()),
    );
    return Promise.resolve({
      models: filtered.slice(query.offset, query.offset + query.limit),
      total: filtered.length,
      selected_count: selected.size,
      candidate_count: pool.length - selected.size,
      families: ["vendor"],
      offset: query.offset,
      limit: query.limit,
    });
  });
  api.removeModel.mockImplementation((_id, modelId) => {
    serverProvider = {
      ...serverProvider,
      models: serverProvider.models.filter((model) => model.id !== modelId),
      extra_models: serverProvider.extra_models.filter(
        (model) => model.id !== modelId,
      ),
      discovered_models: serverProvider.discovered_models?.filter(
        (model) => model.id !== modelId,
      ),
    };
    return Promise.resolve(serverProvider);
  });
  api.updateModelPool.mockResolvedValue(provider);
  api.discoverModels.mockResolvedValue({
    success: true,
    models: [candidate],
    discovered_count: 1,
  });
});
describe("model pool switches", () => {
  it("shows selected and unselected models together with their state", async () => {
    await render();
    expect(
      screen.getByRole("switch", {
        name: "models.pool.selectorToggle New candidate",
      }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("switch", {
        name: "models.pool.selectorToggle Chosen model",
      }),
    ).toBeChecked();
    expect(screen.getByText("New")).toBeInTheDocument();
    expect(screen.getByText(/1M/)).toBeInTheDocument();
  });
  it("enables a candidate without removing its row", async () => {
    api.updateModelPool.mockImplementation((_p, _m, body) =>
      Promise.resolve(
        body.selected
          ? (serverProvider = {
              ...provider,
              extra_models: [chosen, candidate],
            })
          : provider,
      ),
    );
    await render();
    fireEvent.click(
      screen.getByRole("switch", {
        name: "models.pool.selectorToggle New candidate",
      }),
    );
    await waitFor(() =>
      expect(api.updateModelPool).toHaveBeenCalledWith(
        "openrouter",
        candidate.id,
        { selected: true, seen: true },
      ),
    );
    expect(screen.getByText("New candidate")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("switch", {
          name: "models.pool.selectorToggle New candidate",
        }),
      ).toBeChecked(),
    );
  });
  it("disables a selected model without deleting it", async () => {
    api.updateModelPool.mockImplementation(() => {
      serverProvider = {
        ...provider,
        extra_models: [],
        discovered_models: [candidate, chosen],
      };
      return Promise.resolve(serverProvider);
    });
    await render();
    await userEvent.click(
      screen.getByRole("switch", {
        name: "models.pool.selectorToggle Chosen model",
      }),
    );
    await waitFor(() =>
      expect(api.updateModelPool).toHaveBeenCalledWith(
        "openrouter",
        chosen.id,
        { selected: false, seen: true },
      ),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("switch", {
          name: "models.pool.selectorToggle Chosen model",
        }),
      ).not.toBeChecked(),
    );
    expect(screen.getByText("Chosen model")).toBeInTheDocument();
    expect(api.removeModel).not.toHaveBeenCalled();
  });
  it("can enable all after disabling all and refreshing the pool", async () => {
    // Disabled models remain discoverable and can be enabled again.
    serverProvider = { ...provider, discovered_models: [candidate, chosen] };
    api.selectAllModels.mockImplementation((_id, selected) => {
      serverProvider = {
        ...serverProvider,
        extra_models: selected ? [chosen, candidate] : [],
      };
      return Promise.resolve(serverProvider);
    });
    const user = userEvent.setup();
    await render();
    await user.click(
      screen.getByRole("button", {
        name: "models.pool.disableAll",
      }),
    );
    await waitFor(() => {
      expect(
        screen.getByRole("switch", {
          name: "models.pool.selectorToggle Chosen model",
        }),
      ).not.toBeChecked();
      // Query the current DOM: Tooltip may replace its child as disabled changes.
      expect(
        screen.getByRole("button", {
          name: "models.pool.enableAll",
        }),
      ).toBeEnabled();
    });
    await user.click(
      screen.getByRole("button", {
        name: "models.pool.enableAll",
      }),
    );
    await waitFor(() => {
      expect(
        screen.getByRole("switch", {
          name: "models.pool.selectorToggle Chosen model",
        }),
      ).toBeChecked();
      expect(
        screen.getByRole("switch", {
          name: "models.pool.selectorToggle New candidate",
        }),
      ).toBeChecked();
    });
    expect(api.selectAllModels.mock.calls).toEqual([
      ["openrouter", false],
      ["openrouter", true],
    ]);
  });
  it("confirms the full catalog before a large bulk enable", async () => {
    api.getModelPool.mockResolvedValue({
      models: [chosen, candidate],
      total: 2,
      selected_count: 1,
      candidate_count: 11000,
      families: [],
      offset: 0,
      limit: 50,
    });
    api.selectAllModels.mockResolvedValue(provider);
    await render();
    fireEvent.click(
      screen.getByRole("button", { name: "models.pool.enableAll" }),
    );
    expect(api.selectAllModels).not.toHaveBeenCalled();
    expect(
      screen.getByText("models.pool.enableAllConfirm"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() =>
      expect(api.selectAllModels).toHaveBeenCalledWith("openrouter", true),
    );
  });
  it("updates OpenRouter through the common refresh action", async () => {
    const { onSaved } = await render();
    fireEvent.click(
      screen.getByRole("button", { name: "models.autoDiscoverModels" }),
    );
    await waitFor(() =>
      expect(api.discoverModels).toHaveBeenCalledWith(
        "openrouter",
        undefined,
        true,
      ),
    );
    expect(onSaved).toHaveBeenCalled();
    expect(api.addModel).not.toHaveBeenCalled();
  });
  it("preserves existing rows when refresh fails", async () => {
    api.discoverModels.mockResolvedValue({
      success: false,
      message: "Authentication failed",
      models: [],
    });
    await render();
    fireEvent.click(
      screen.getByRole("button", { name: "models.autoDiscoverModels" }),
    );
    await waitFor(() =>
      expect(message.error).toHaveBeenCalledWith("Authentication failed"),
    );
    expect(screen.getByText("New candidate")).toBeInTheDocument();
  });
  it("clears New after a deliberate hover", async () => {
    await render();
    fireEvent.mouseEnter(
      screen.getByText("New candidate").closest("[data-model-id]")!,
    );
    await waitFor(() =>
      expect(api.updateModelPool).toHaveBeenCalledWith(
        "openrouter",
        candidate.id,
        { seen: true },
      ),
    );
    expect(screen.queryByText("New")).not.toBeInTheDocument();
  });
  it("does not clear New while the pointer merely passes over", async () => {
    await render();
    const row = screen.getByText("New candidate").closest("[data-model-id]")!;
    fireEvent.mouseEnter(row);
    fireEvent.mouseLeave(row);
    await new Promise((resolve) => setTimeout(resolve, 650));
    expect(api.updateModelPool).not.toHaveBeenCalled();
  });
  it("tests an unselected model without selecting it", async () => {
    api.testModelConnection.mockResolvedValue({ success: true });
    await render();
    const row = screen.getByText("New candidate").closest("[data-model-id]")!;
    fireEvent.click(
      within(row as HTMLElement).getByRole("button", {
        name: "models.testConnection",
      }),
    );
    await waitFor(() =>
      expect(api.testModelConnection).toHaveBeenCalledWith("openrouter", {
        model_id: candidate.id,
      }),
    );
    expect(
      api.updateModelPool.mock.calls.every(
        (call) => call[2].selected === undefined,
      ),
    ).toBe(true);
  });
  it("allows configuring an unselected model", async () => {
    await render();
    const row = screen.getByText("New candidate").closest("[data-model-id]")!;
    fireEvent.click(
      within(row as HTMLElement).getByRole("button", {
        name: "models.modelConfigLabel",
      }),
    );
    expect(screen.getByText("configuration")).toBeInTheDocument();
    expect(
      api.updateModelPool.mock.calls.every(
        (call) => call[2].selected === undefined,
      ),
    ).toBe(true);
  });
  it("retains rows while a new search page is pending", async () => {
    await render();
    api.getModelPool.mockReturnValue(new Promise(() => {}));
    fireEvent.change(
      screen.getByRole("textbox", { name: "models.searchModelPlaceholder" }),
      { target: { value: "vision" } },
    );
    await waitFor(() =>
      expect(api.getModelPool).toHaveBeenLastCalledWith(
        "openrouter",
        expect.objectContaining({ search: "vision", offset: 0, limit: 30 }),
      ),
    );
    expect(screen.getByText("New candidate")).toBeInTheDocument();
    expect(screen.getByText("Chosen model")).toBeInTheDocument();
  });
  it("allows personal selection from the organization candidate pool", async () => {
    await render({ id: "hub-managed" });
    expect(screen.getByText("Chosen model")).toBeInTheDocument();
    expect(api.getModelPool).toHaveBeenCalledWith(
      "hub-managed",
      expect.objectContaining({ tab: "all" }),
    );
    fireEvent.click(
      screen.getByRole("switch", {
        name: "models.pool.selectorToggle New candidate",
      }),
    );
    await waitFor(() =>
      expect(api.updateModelPool).toHaveBeenCalledWith(
        "hub-managed",
        "vendor/free",
        { selected: true, seen: true },
      ),
    );
    expect(
      screen.queryByRole("button", { name: "models.modelConfigLabel" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("models.autoDiscoverModels"),
    ).not.toBeInTheDocument();
  });
  it("combines quick filters and keeps advanced filters out of the toolbar", async () => {
    await render({ id: "deepseek" });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "models.billing.free" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "models.tagMultimodal" }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "models.pool.capabilityOptions.tool_calling",
      }),
    );
    await waitFor(() =>
      expect(api.getModelPool).toHaveBeenLastCalledWith(
        "deepseek",
        expect.objectContaining({
          billing: "free",
          multimodal: true,
          tools: true,
          offset: 0,
        }),
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "models.pool.moreFilters" }),
    );
    expect(
      await screen.findByRole("group", {
        name: "models.pool.filterLabels.availability",
      }),
    ).toBeInTheDocument();
  });
  it("filters only enabled models without changing their selection", async () => {
    await render();
    fireEvent.click(
      screen.getByRole("switch", { name: "models.pool.onlyEnabled" }),
    );
    await waitFor(() =>
      expect(api.getModelPool).toHaveBeenLastCalledWith(
        "openrouter",
        expect.objectContaining({ tab: "selected", offset: 0 }),
      ),
    );
    expect(api.updateModelPool).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByText("New candidate")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Chosen model")).toBeInTheDocument();
  });
  it("offers manual addition for OpenRouter", async () => {
    await render();
    fireEvent.click(screen.getByText("models.addModel"));
    expect(screen.getAllByRole("dialog")).toHaveLength(2);
  });
});

describe("model pool removal", () => {
  const clickRemove = (name: string) => {
    const row = screen.getByText(name).closest("[data-model-id]")!;
    fireEvent.click(
      within(row as HTMLElement).getByRole("button", {
        name: "models.removeModel",
      }),
    );
  };

  it.each([chosen, candidate])(
    "removes $name only after confirmation",
    async (model) => {
      const { onSaved, onProviderUpdated } = await render();
      clickRemove(model.name);
      expect(screen.getByText("models.removeModelConfirm")).toBeInTheDocument();
      expect(api.removeModel).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "confirm" }));
      await waitFor(() =>
        expect(api.removeModel).toHaveBeenCalledExactlyOnceWith(
          provider.id,
          model.id,
        ),
      );
      await waitFor(() =>
        expect(screen.queryByText(model.name)).not.toBeInTheDocument(),
      );
      expect(onProviderUpdated).toHaveBeenCalledWith(serverProvider);
      expect(onSaved).toHaveBeenCalledOnce();
      expect(message.success).toHaveBeenCalledWith("models.modelRemoved");
      expect(
        api.updateModelPool.mock.calls.every(
          (call) => call[2].selected === undefined,
        ),
      ).toBe(true);
    },
  );

  it("keeps the model when removal is cancelled", async () => {
    await render();
    clickRemove(chosen.name);
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(
      screen.queryByText("models.removeModelConfirm"),
    ).not.toBeInTheDocument();
    expect(screen.getByText(chosen.name)).toBeInTheDocument();
    expect(api.removeModel).not.toHaveBeenCalled();
  });

  it("retains the model and allows retry after a removal error", async () => {
    api.removeModel.mockRejectedValueOnce(new Error("Removal failed"));
    const { onSaved } = await render();
    clickRemove(chosen.name);
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() =>
      expect(message.error).toHaveBeenCalledWith("Removal failed"),
    );
    expect(screen.getByText(chosen.name)).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() =>
      expect(screen.queryByText(chosen.name)).not.toBeInTheDocument(),
    );
    expect(api.removeModel).toHaveBeenCalledTimes(2);
  });

  it("blocks duplicate removal and discovery while deletion is pending", async () => {
    let finish!: (value: ProviderInfo) => void;
    api.removeModel.mockReturnValue(
      new Promise<ProviderInfo>((resolve) => {
        finish = resolve;
      }),
    );
    await render();
    clickRemove(chosen.name);
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    expect(screen.getByRole("button", { name: "confirm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "cancel" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "models.autoDiscoverModels" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    expect(api.removeModel).toHaveBeenCalledOnce();
    await act(async () => finish({ ...provider, extra_models: [] }));
  });

  it("removes the stale row immediately while the refreshed pool is pending", async () => {
    await render();
    api.getModelPool.mockReturnValue(new Promise(() => {}));
    clickRemove(chosen.name);
    fireEvent.click(screen.getByRole("button", { name: "confirm" }));
    await waitFor(() =>
      expect(screen.queryByText(chosen.name)).not.toBeInTheDocument(),
    );
    expect(screen.getByText(candidate.name)).toBeInTheDocument();
    await waitFor(() => expect(api.getModelPool).toHaveBeenCalledTimes(2));
  });

  it("does not expose removal for organization-managed models", async () => {
    await render({ id: "hub-managed" });
    expect(
      screen.queryByRole("button", { name: "models.removeModel" }),
    ).not.toBeInTheDocument();
  });
});
