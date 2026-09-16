import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useEmbeddingVerification } from "./useEmbeddingVerification";
import { useEmbeddingVerificationStore } from "@/stores/embeddingVerificationStore";
import { useAgentStore } from "@/stores/agentStore";

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: vi.fn(),
}));

vi.mock("./embeddingUtils", () => ({
  getEmbeddingServiceFingerprint: vi.fn((config) =>
    config ? `${config.backend}-${config.model_name}` : "",
  ),
}));

describe("useEmbeddingVerification - GH#7226", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useEmbeddingVerificationStore.setState({ verificationByAgent: {} });
    vi.mocked(useAgentStore).mockReturnValue({
      selectedAgent: "test-agent",
    } as any);
  });

  it("should persist verification result in zustand store", () => {
    const { result } = renderHook(() =>
      useEmbeddingVerification(
        { backend: "openai", model_name: "text-embedding-3-small" } as any,
        true,
      ),
    );

    act(() => {
      result.current.markVerified(1536, 245);
    });

    const storeState = useEmbeddingVerificationStore.getState();
    expect(storeState.verificationByAgent["test-agent"]).toBeDefined();
    expect(storeState.verificationByAgent["test-agent"].dimensions).toBe(1536);
    expect(storeState.verificationByAgent["test-agent"].latency).toBe(245);
  });

  it("should retrieve verification result after re-render (simulating page navigation)", () => {
    const { result: result1, unmount } = renderHook(() =>
      useEmbeddingVerification(
        { backend: "openai", model_name: "text-embedding-3-small" } as any,
        true,
      ),
    );

    act(() => {
      result1.current.markVerified(1536, 245);
    });

    // Leave the page: the whole component tree goes away. The verified
    // result must survive in the store, not in component state.
    unmount();

    // Come back: a brand new hook instance has to read the result back.
    const { result: result2 } = renderHook(() =>
      useEmbeddingVerification(
        { backend: "openai", model_name: "text-embedding-3-small" } as any,
        true,
      ),
    );

    expect(result2.current.testedEmbedding).toBeDefined();
    expect(result2.current.testedEmbeddingIsCurrent).toBe(true);
  });

  it("should invalidate verification when config fingerprint changes", () => {
    const { result } = renderHook(() =>
      useEmbeddingVerification(
        { backend: "openai", model_name: "text-embedding-3-small" } as any,
        true,
      ),
    );

    act(() => {
      result.current.markVerified(1536, 245);
    });

    // Re-render with different config
    const { result: result2 } = renderHook(() =>
      useEmbeddingVerification(
        { backend: "dashscope", model_name: "text-embedding-v2" } as any,
        true,
      ),
    );

    expect(result2.current.testedEmbeddingIsCurrent).toBe(false);
  });

  it("should clear verification when embedding is disabled", () => {
    const { result, rerender } = renderHook(
      ({ enabled }) =>
        useEmbeddingVerification(
          { backend: "openai", model_name: "text-embedding-3-small" } as any,
          enabled,
        ),
      { initialProps: { enabled: true } },
    );

    act(() => {
      result.current.markVerified(1536, 245);
    });

    expect(
      useEmbeddingVerificationStore.getState().verificationByAgent[
        "test-agent"
      ],
    ).toBeDefined();

    // Disable embedding
    rerender({ enabled: false });

    expect(
      useEmbeddingVerificationStore.getState().verificationByAgent[
        "test-agent"
      ],
    ).toBeUndefined();
  });
});
