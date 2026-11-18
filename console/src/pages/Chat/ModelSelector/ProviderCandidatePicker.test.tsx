import { expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import type { ModelInfo, ProviderInfo } from "../../../api/types";
import { providerApi } from "../../../api/modules/provider";
import ProviderCandidatePicker from "./ProviderCandidatePicker";
vi.mock("../../../api/modules/provider", () => ({
  providerApi: { getModelPool: vi.fn(), updateModelPool: vi.fn() },
}));
it("fetches candidates for the chosen provider and adds inline", async () => {
  vi.mocked(providerApi.getModelPool).mockResolvedValue({
    models: [
      {
        id: "new-model",
        name: "New Model",
        billing: "free",
        supports_image: true,
        supports_tool_calling: true,
      } as ModelInfo,
    ],
    total: 1,
    offset: 0,
    limit: 10,
    selected_count: 1,
    candidate_count: 1,
    families: [],
  });
  vi.mocked(providerApi.updateModelPool).mockResolvedValue({} as ProviderInfo);
  const saved = vi.fn().mockResolvedValue(undefined);
  renderWithProviders(
    <ProviderCandidatePicker
      providerId="openrouter"
      tier="free"
      onSaved={saved}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "modelSelector.addToSelector New Model",
    }),
  );
  await waitFor(() =>
    expect(providerApi.updateModelPool).toHaveBeenCalledWith(
      "openrouter",
      "new-model",
      { selected: true, seen: true },
    ),
  );
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(providerApi.getModelPool).toHaveBeenCalledWith(
    "openrouter",
    expect.objectContaining({ tab: "candidates", billing: "free", limit: 10 }),
  );
  expect(
    screen.getByRole("img", { name: "models.billing.free" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: "models.tagVision" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("img", {
      name: "models.pool.capabilityOptions.tool_calling",
    }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
