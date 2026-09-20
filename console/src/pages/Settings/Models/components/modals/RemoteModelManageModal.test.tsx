import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import type { ProviderInfo, ModelInfo } from "../../../../../api/types";
import { RemoteModelManageModal } from "./RemoteModelManageModal";
const api = vi.hoisted(() => ({
  getModelPool: vi.fn(),
  updateModelPool: vi.fn(),
  discoverModels: vi.fn(),
  addModel: vi.fn(),
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
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
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
    Modal: ({ open, children, title, onOk }: any) =>
      open ? (
        <div role="dialog">
          <h2>{title}</h2>
          {children}
          {onOk && <button onClick={onOk}>confirm</button>}
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
  renderWithProviders(
    <RemoteModelManageModal
      provider={{ ...provider, ...providerOverride }}
      open
      onClose={vi.fn()}
      onSaved={onSaved}
    />,
  );
  await waitFor(() => expect(api.getModelPool).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.queryByText("common.loading")).not.toBeInTheDocument(),
  );
  return { onSaved };
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
    expect(screen.getByText(/1,000,000/)).toBeInTheDocument();
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
    await render();
    fireEvent.click(
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
    expect(screen.getByText("Chosen model")).toBeInTheDocument();
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
