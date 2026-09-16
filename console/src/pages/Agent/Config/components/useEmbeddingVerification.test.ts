import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useAgentStore } from "@/stores/agentStore";
import { useEmbeddingVerification } from "./useEmbeddingVerification";

const config = {
  backend: "openai" as const,
  api_key: "secret",
  base_url: "https://example.com/v1",
  model_name: "embedding-model",
  dimensions: 1024,
  enable_cache: true,
  use_dimensions: false,
  max_cache_size: 10000,
  max_input_length: 8192,
  max_batch_size: 10,
};

afterEach(() => {
  useAgentStore.setState({ selectedAgent: "default" });
});

describe("useEmbeddingVerification", () => {
  it("keeps verification bound to the governed agent instead of the sidebar agent", () => {
    useAgentStore.setState({ selectedAgent: "sidebar-agent" });
    const requestContext = {
      agentId: "governed-agent",
      governance: true,
    } as const;
    const { result } = renderHook(() =>
      useEmbeddingVerification(config, true, 7, requestContext),
    );

    act(() => result.current.markVerified(1024, 25));
    expect(result.current.testedEmbedding).toMatchObject({
      agentId: "governed-agent",
      dimensions: 1024,
    });
    expect(result.current.testedEmbeddingIsCurrent).toBe(true);

    act(() => useAgentStore.setState({ selectedAgent: "another-sidebar" }));
    expect(result.current.testedEmbeddingIsCurrent).toBe(true);
  });
});
