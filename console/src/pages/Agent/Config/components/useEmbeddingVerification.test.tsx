import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { EmbeddingModelConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useEmbeddingVerificationStore } from "@/stores/embeddingVerificationStore";
import { isEmbeddingEnabled } from "./embeddingUtils";
import { useEmbeddingVerification } from "./useEmbeddingVerification";

const enabledConfig: EmbeddingModelConfig = {
  backend: "openai",
  model_name: "text-embedding-v4",
  api_key: "secret",
  base_url: "",
  dimensions: 1024,
  enable_cache: true,
  use_dimensions: true,
  max_cache_size: 1000,
  max_input_length: 8192,
  max_batch_size: 10,
  health_check_timeout: 15,
};

const disabledConfig: EmbeddingModelConfig = {
  ...enabledConfig,
  model_name: "",
  api_key: "",
};

function renderVerificationHook(config: EmbeddingModelConfig) {
  return renderHook(
    ({ currentConfig }) =>
      useEmbeddingVerification(
        currentConfig,
        isEmbeddingEnabled(currentConfig),
      ),
    { initialProps: { currentConfig: config } },
  );
}

afterEach(() => {
  useAgentStore.setState({ selectedAgent: "default" });
  useEmbeddingVerificationStore.setState({ verificationByAgent: {} });
});

describe("useEmbeddingVerification", () => {
  it("preserves the selected agent verification during a mixed config frame", () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    act(() => result.current.markVerified(1024, 50));
    expect(
      useEmbeddingVerificationStore.getState().verificationByAgent.default,
    ).toBeDefined();

    act(() => useAgentStore.setState({ selectedAgent: "disabled-agent" }));
    rerender({ currentConfig: disabledConfig });

    // selectedAgent changes synchronously, while the form still contains the
    // disabled agent's values until its asynchronous config load completes.
    act(() => useAgentStore.setState({ selectedAgent: "default" }));

    expect(
      useEmbeddingVerificationStore.getState().verificationByAgent.default,
    ).toBeDefined();

    rerender({ currentConfig: enabledConfig });
    expect(result.current.testedEmbeddingIsCurrent).toBe(true);
  });

  it("still clears verification when the same agent becomes disabled", () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    act(() => result.current.markVerified(1024, 50));
    rerender({ currentConfig: disabledConfig });

    expect(
      useEmbeddingVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
  });
});
