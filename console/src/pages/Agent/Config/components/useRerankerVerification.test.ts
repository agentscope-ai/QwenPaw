/**
 * useRerankerVerification — history loading lifecycle regressions:
 * loading history must never manufacture a successful verification, must
 * never erase a completed manual result, and a multiplier-only change must
 * not refetch-and-clear the current precision.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  getRerankerHistory: vi.fn(),
}));

vi.mock("../../../api", () => ({
  default: {
    getRerankerHistory: (...a: unknown[]) => mocks.getRerankerHistory(...a),
  },
}));

import { useRerankerVerificationStore } from "@/stores/rerankerVerificationStore";
import { useRerankerVerification } from "./useRerankerVerification";
import type { RerankerConfig } from "@/api/types/agent";

const baseConfig: RerankerConfig = {
  enabled: true,
  api_key: "k",
  base_url: "https://api.example.com/v1",
  model_name: "m",
  candidate_multiplier: 3,
  timeout: 10,
  auto_verify_interval_hours: 0,
};

const historyRecord = {
  ts: 1_700_000_000_000,
  latency_ms: 120,
  precision: 0.8,
  correct_count: 4,
  total: 5,
};

describe("useRerankerVerification history lifecycle", () => {
  beforeEach(() => {
    useRerankerVerificationStore.setState({ verificationByAgent: {} });
    mocks.getRerankerHistory.mockReset();
    mocks.getRerankerHistory.mockResolvedValue({ history: [] });
  });

  it("history-only load does not display a fabricated verification", async () => {
    const { result } = renderHook(() =>
      useRerankerVerification(baseConfig, true),
    );

    await act(async () => {
      await result.current.setHistory([historyRecord]);
    });

    const stored =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(stored).toBeDefined();
    expect(stored?.verifiedAt).toBe(0);
    expect(stored?.latency).toBe(0);
    expect(stored?.precision).toBeNull();
    expect(stored?.history).toHaveLength(1);
  });

  it("a late history response does not erase a completed manual result", async () => {
    const { result } = renderHook(() =>
      useRerankerVerification(baseConfig, true),
    );

    await act(async () => {
      await result.current.markVerified(321, 1.0, 5, 5, []);
    });
    const manual =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(manual?.verifiedAt).toBeGreaterThan(0);

    await act(async () => {
      await result.current.setHistory([historyRecord]);
    });

    const after =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(after?.verifiedAt).toBe(manual?.verifiedAt);
    expect(after?.latency).toBe(321);
    expect(after?.precision).toBe(1.0);
    // History series refreshed, verification result preserved.
    expect(after?.history).toHaveLength(1);
  });

  it("empty history stores nothing misleading (precision slot stays empty)", async () => {
    const { result } = renderHook(() =>
      useRerankerVerification(baseConfig, true),
    );

    await act(async () => {
      await result.current.setHistory([]);
    });

    const stored =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(stored?.verifiedAt).toBe(0);
    expect(stored?.precision).toBeNull();
  });

  it("multiplier-only change keeps verification fingerprint stable", async () => {
    const { result, rerender } = renderHook(
      ({ config }: { config: RerankerConfig }) =>
        useRerankerVerification(config, true),
      { initialProps: { config: baseConfig } },
    );

    await act(async () => {
      await result.current.markVerified(321, 1.0, 5, 5, []);
    });
    const before =
      useRerankerVerificationStore.getState().verificationByAgent.default;

    rerender({ config: { ...baseConfig, candidate_multiplier: 5 } });

    const after =
      useRerankerVerificationStore.getState().verificationByAgent.default;
    expect(after?.fingerprint).toBe(before?.fingerprint);
    expect(after?.verifiedAt).toBe(before?.verifiedAt);
  });
});
