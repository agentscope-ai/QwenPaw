/**
 * useRerankerVerification — verdict lifecycle and history loading.
 *
 * Loading history must never manufacture a successful verification, must never
 * erase a completed manual result, and a multiplier-only change must not
 * invalidate the stored verdict.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { RerankerConfig } from "@/api/types/agent";
import { useAgentStore } from "@/stores/agentStore";
import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { isRerankerConfigured } from "./rerankerUtils";
import { useRerankerVerification } from "./useRerankerVerification";

// Generated per run so no credential-like literal is committed.
const TEST_API_KEY = `probe-${crypto.randomUUID().replace(/-/g, "")}`;

const enabledConfig: RerankerConfig = {
  enabled: true,
  api_key: TEST_API_KEY,
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

const historyRecord = {
  ts: 1_700_000_000_000,
  latency_ms: 120,
  precision: 0.8,
  correct_count: 4,
  total: 5,
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
  useRerankerVerificationStore.setState({
    verificationByAgent: {},
    historyByAgent: {},
  });
});

describe("useRerankerVerification", () => {
  it("stores latency and the ranking verdict for the agent", async () => {
    const { result } = renderVerificationHook(enabledConfig);

    await act(async () => result.current.markVerified(320, 1, 3, 3));

    const stored =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(stored).toMatchObject({
      latency: 320,
      precision: 1,
      correctCount: 3,
      total: 3,
    });
    expect(result.current.testedRerankerIsCurrent).toBe(true);
  });

  it("preserves the selected agent verification during a mixed config frame", async () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    await act(async () => result.current.markVerified(320, 1, 3, 3));
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

  it("still clears verification when the same agent becomes disabled", async () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    await act(async () => result.current.markVerified(320, 1, 3, 3));
    rerender({ currentConfig: disabledConfig });

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
  });

  it("invalidates the stored verdict when the service config changes", async () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    await act(async () => result.current.markVerified(320, 1, 3, 3));
    rerender({
      currentConfig: { ...enabledConfig, model_name: "other-reranker-model" },
    });

    // The fingerprint resolves asynchronously, so the invalidation lands a
    // tick after the rerender.
    await waitFor(() =>
      expect(result.current.testedRerankerIsCurrent).toBe(false),
    );
  });

  it("history-only load does not manufacture a verification", async () => {
    const { result } = renderVerificationHook(enabledConfig);

    await act(async () => {
      await result.current.setHistory([historyRecord]);
    });

    // No verdict exists at all: history lives in its own slice.
    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
    expect(result.current.history).toHaveLength(1);
  });

  it("empty history leaves both slices empty", async () => {
    const { result } = renderVerificationHook(enabledConfig);

    await act(async () => {
      await result.current.setHistory([]);
    });

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent.default).toBeUndefined();
    expect(result.current.history).toEqual([]);
  });

  it("drops history and verdicts for a superseded service config", async () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);
    await waitFor(() =>
      expect(result.current.serviceFingerprint).toMatch(/^sha256:/),
    );
    const staleFingerprint = result.current.serviceFingerprint;

    rerender({
      currentConfig: { ...enabledConfig, model_name: "changed-reranker" },
    });
    await waitFor(() =>
      expect(result.current.serviceFingerprint).not.toBe(staleFingerprint),
    );

    await act(async () => {
      await result.current.setHistory([historyRecord], staleFingerprint);
      await result.current.markVerified(321, 1, 5, 5, staleFingerprint);
    });

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toBeUndefined();
    expect(result.current.history).toEqual([]);
  });

  it("a late history response does not erase a completed manual result", async () => {
    const { result } = renderVerificationHook(enabledConfig);

    await act(async () => {
      await result.current.markVerified(321, 1.0, 5, 5);
    });
    const manual =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(manual?.verifiedAt).toBeGreaterThan(0);

    await act(async () => {
      await result.current.setHistory([historyRecord]);
    });

    expect(
      useRerankerVerificationStore.getState().verificationByAgent.default,
    ).toEqual(manual);
    expect(result.current.history).toHaveLength(1);
  });

  it("a delayed history read cannot overwrite a newer series", async () => {
    const { result } = renderVerificationHook(enabledConfig);
    const older = { ...historyRecord, ts: 1_000, precision: 0.2 };
    const newer = { ...historyRecord, ts: 2_000, precision: 1.0 };

    // The manual probe response already carries the freshly appended series.
    await act(async () => {
      await result.current.markVerified(321, 1.0, 5, 5);
      await result.current.setHistory([older, newer]);
    });
    expect(result.current.history.map((entry) => entry.ts)).toEqual([
      1_000, 2_000,
    ]);

    // A GET that started earlier resolves afterwards with the stale series.
    await act(async () => {
      await result.current.setHistory([older]);
    });

    expect(result.current.history.map((entry) => entry.ts)).toEqual([
      1_000, 2_000,
    ]);
  });

  it("multiplier-only change keeps verification fingerprint stable", async () => {
    const { result, rerender } = renderVerificationHook(enabledConfig);

    await act(async () => {
      await result.current.markVerified(321, 1.0, 5, 5);
    });
    const before =
      useRerankerVerificationStore.getState().verificationByAgent.default;

    rerender({ currentConfig: { ...enabledConfig, candidate_multiplier: 5 } });
    await waitFor(() =>
      expect(result.current.serviceFingerprint).toBe(before?.fingerprint),
    );

    const after =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(after?.fingerprint).toBe(before?.fingerprint);
    expect(after?.verifiedAt).toBe(before?.verifiedAt);
    expect(after?.precision).toBe(1.0);
  });
});