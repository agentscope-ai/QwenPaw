import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const hoisted = vi.hoisted(() => ({
  apiMocks: {
    listProviders: vi.fn(),
    getActiveModels: vi.fn(),
  },
}));

vi.mock("../../../api", () => ({
  __esModule: true,
  default: hoisted.apiMocks,
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "agent-1" }),
}));

import { useProviders } from "./useProviders";

const { apiMocks } = hoisted;

describe("useProviders", () => {
  beforeEach(() => {
    apiMocks.listProviders.mockReset();
    apiMocks.getActiveModels.mockReset();
  });

  it("loads providers and active models on mount", async () => {
    const providers = [{ provider: "openai" }];
    const active = { models: [] };
    apiMocks.listProviders.mockResolvedValue(providers);
    apiMocks.getActiveModels.mockResolvedValue(active);

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.providers).toEqual(providers);
    expect(result.current.activeModels).toEqual(active);
    expect(apiMocks.getActiveModels).toHaveBeenCalledWith({ scope: "global" });
  });

  it("sets error with 'Unexpected API response' when listProviders returns non-array", async () => {
    apiMocks.listProviders.mockResolvedValue({ not: "array" });
    apiMocks.getActiveModels.mockResolvedValue({});

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.error).toContain("Unexpected API response");
    });
    expect(result.current.loading).toBe(false);
  });

  it("sets error message on fetch failure", async () => {
    apiMocks.listProviders.mockRejectedValue(new Error("fetch failed"));
    apiMocks.getActiveModels.mockResolvedValue({});

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.error).toBe("fetch failed");
    });
  });

  it("uses fallback message when rejection is not an Error", async () => {
    apiMocks.listProviders.mockRejectedValue("oops");
    apiMocks.getActiveModels.mockResolvedValue({});

    const { result } = renderHook(() => useProviders());

    await waitFor(() => {
      expect(result.current.error).toBe("Failed to load provider data");
    });
  });
});
