import { renderWithProviders } from "@/test/common_setup";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  setActiveLlm: vi.fn(),
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: {
    setActiveLlm: apiMocks.setActiveLlm,
  },
}));

vi.mock("../../Chat/ModelSelector/ModelChoice", () => ({
  ModelChoice: ({
    ariaLabel,
    modelType,
    onChange,
  }: {
    ariaLabel: string;
    modelType: "chat" | "decision";
    onChange: (slot: { provider_id: string; model: string }) => void;
  }) => (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={() =>
        onChange({
          provider_id: `${modelType}-provider`,
          model: `${modelType}-v1`,
        })
      }
    >
      {ariaLabel}
    </button>
  ),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { GlobalModelDefaults } from "./GlobalModelDefaults";

describe("GlobalModelDefaults", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.setActiveLlm.mockResolvedValue(undefined);
  });

  it("saves the selected global decision model", async () => {
    const onSaved = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(
      <GlobalModelDefaults
        activeModels={{
          active_llm: null,
          default_models: { chat: null, decision: null },
        }}
        providers={[]}
        onSaved={onSaved}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "models.defaultDecisionModel" }),
    );

    await waitFor(() => expect(apiMocks.setActiveLlm).toHaveBeenCalledOnce());
    expect(apiMocks.setActiveLlm).toHaveBeenCalledWith({
      scope: "global",
      model_type: "decision",
      provider_id: "decision-provider",
      model: "decision-v1",
    });
    expect(onSaved).toHaveBeenCalledOnce();
  });
});
