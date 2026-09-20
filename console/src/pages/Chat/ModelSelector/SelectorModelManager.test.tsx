import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import type { ModelInfo, ProviderInfo } from "../../../api/types";
import { providerApi } from "../../../api/modules/provider";
import SelectorModelManager from "./SelectorModelManager";
vi.mock("../../../api/modules/provider", () => ({
  providerApi: { getModelPool: vi.fn(), updateModelPool: vi.fn() },
}));
vi.mock("../../Settings/Models/components/ProviderIconComponent", () => ({
  ProviderIcon: ({ providerId }: { providerId: string }) => (
    <span>{providerId}-logo</span>
  ),
}));
const first = {
  id: "one",
  name: "Provider One",
  models: [{ id: "selected-a", name: "Selected A" }],
  extra_models: [],
  discovered_models: [{ id: "candidate", name: "Candidate" } as ModelInfo],
} as unknown as ProviderInfo;
const second = {
  ...first,
  id: "two",
  name: "Provider Two",
  models: [{ id: "selected-b", name: "Selected B" }],
} as ProviderInfo;
const saved = vi.fn().mockResolvedValue(undefined);
const updated = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(providerApi.getModelPool).mockResolvedValue({
    models: [{ id: "candidate", name: "Candidate" } as ModelInfo],
    total: 1,
    selected_count: 1,
    candidate_count: 1,
    families: [],
    offset: 0,
    limit: 30,
  });
  vi.mocked(providerApi.updateModelPool).mockResolvedValue({
    ...first,
    models: [],
  });
});
function renderEditor() {
  return renderWithProviders(
    <SelectorModelManager
      providers={[first, second]}
      onClose={vi.fn()}
      onSaved={saved}
      onProviderUpdated={updated}
    />,
  );
}
it("shows only selected models across providers inline", () => {
  renderEditor();
  expect(screen.getByText("Selected A")).toBeInTheDocument();
  expect(screen.getByText("Selected B")).toBeInTheDocument();
  expect(screen.queryByText("Candidate")).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(providerApi.getModelPool).not.toHaveBeenCalled();
});
it("removes a selected model and refreshes the selector", async () => {
  renderEditor();
  fireEvent.click(
    screen.getByRole("button", {
      name: "modelSelector.removeFromSelector Selected A",
    }),
  );
  await waitFor(() =>
    expect(providerApi.updateModelPool).toHaveBeenCalledWith(
      "one",
      "selected-a",
      { selected: false, seen: true },
    ),
  );
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(updated).toHaveBeenCalled();
});
it("chooses a provider before fetching candidates and adding a model", async () => {
  renderEditor();
  fireEvent.click(screen.getByRole("button", { name: "models.addModel" }));
  expect(providerApi.getModelPool).not.toHaveBeenCalled();
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByText("Provider Two"));
  await waitFor(() =>
    expect(providerApi.getModelPool).toHaveBeenCalledWith(
      "two",
      expect.objectContaining({ tab: "candidates", limit: 30 }),
    ),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "modelSelector.addToSelector Candidate",
    }),
  );
  await waitFor(() =>
    expect(providerApi.updateModelPool).toHaveBeenCalledWith(
      "two",
      "candidate",
      { selected: true, seen: true },
    ),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
