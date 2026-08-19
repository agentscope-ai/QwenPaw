import { describe, expect, it, vi } from "vitest";

import { loadModelSelectorData } from "./modelSelectorApi";

describe("loadModelSelectorData", () => {
  it("does not replace providers when their request fails", async () => {
    const activeModels = { active_llm: null };
    const dataSource = {
      listProviders: vi
        .fn()
        .mockRejectedValue(new Error("providers unavailable")),
      getActiveModels: vi.fn().mockResolvedValue(activeModels),
    };

    const result = await loadModelSelectorData("default", dataSource);

    expect(result).toEqual({
      providers: null,
      activeModels,
      loadError: true,
    });
  });
});
