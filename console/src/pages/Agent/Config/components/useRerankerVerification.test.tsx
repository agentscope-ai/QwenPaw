import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { RerankerConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { isRerankerConfigured } from "./rerankerUtils";
import { useRerankerVerification } from "./useRerankerVerification";

const enabledConfig: RerankerConfig = {
  enabled: true,
  api_key: "secret",
  base_url: "https://api.siliconflow.cn/v1",
  model_name: "BAAI/bge-reranker-v2-m3",
  candidate_multiplier: 3,
  timeout: 10,
  auto_verify_interval_hours: 0,
};

const disabledConfig: RerankerConfig = {
  ...enabledConfig,
  enabled: false,
};

function renderVerificationHook(config: RerankerConfig) {
  return renderHook(
    ({ currentConfig }) =>
      useRerankerVerification(
        currentConfig,
        isRerankerConfigured(currentConfig),
      ),
    { initialProps: { currentConfig: config } },
  );
}

afterEach(() => {
  useAgentStore.setState({ selectedAgent: "default" });
  useRerankerVerificationStore.setState({ verificationByAgent: {} });
});

describe("useRerankerVerification", () => {
  it("stores latency and the ranking verdict for the agent", () => {
    const { result } = renderVerificationHook(enabledConfig);

    act(() => result.current.markVerified(320, 1, 3, 3, []));

    const stored =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(stored).toMatchObject({
      latency: 320,
      precision: 1,
      correctCount: 3,
      total: 3,
      history: [],
    });
    expect(result.current.testedRerankerIsCurrent).toBe(true);
  });

  it("preserves the selected agent verification during a mixed config frame", () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    act(() => result.current.markVerified(320, 1, 3, 3, []));
    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeDefined();

    act(() => useAgentStore.setState({ selectedAgent: "other-agent" }));
    rerender({ currentConfig: disabledConfig });

    // selectedAgent changes synchronously, while the form still contains the
    // previous agent's values until its asynchronous config load completes.
    act(() => useAgentStore.setState({ selectedAgent: "default" }));

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeDefined();

    rerender({ currentConfig: enabledConfig });
    expect(result.current.testedRerankerIsCurrent).toBe(true);
  });

  it("still clears verification when the same agent becomes disabled", () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    act(() => result.current.markVerified(320, 1, 3, 3, []));
    rerender({ currentConfig: disabledConfig });

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
  });

  it("invalidates the stored verdict when the service config changes", () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    act(() => result.current.markVerified(320, 1, 3, 3, []));
    rerender({
      currentConfig: { ...enabledConfig, model_name: "other-reranker-model" },
    });

    expect(result.current.testedRerankerIsCurrent).toBe(false);
  });
});
