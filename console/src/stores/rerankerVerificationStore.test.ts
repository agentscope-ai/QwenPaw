import { describe, it, expect, beforeEach } from "vitest";
import { useRerankerVerificationStore } from "./rerankerVerificationStore";

const configKey = JSON.stringify([
  "https://api.example.com/v1",
  "",
  "fixture-model",
  "10",
]);

const otherConfigKey = JSON.stringify([
  "https://api.example.com/v1",
  "",
  "other-model",
  "10",
]);

const fingerprintA = `sha256:${"a".repeat(64)}`;
const fingerprintB = `sha256:${"b".repeat(64)}`;

const verification = {
  configKey,
  latency: 320,
  precision: 1,
  correctCount: 3,
  total: 3,
  verifiedAt: 1_700_000_000_000,
};

const historyRecord = {
  ts: 1_700_000_000_000,
  latency_ms: 120,
  precision: 0.8,
  correct_count: 4,
  total: 5,
};

describe("rerankerVerificationStore", () => {
  beforeEach(() => {
    // Reset store state before each test
    useRerankerVerificationStore.setState({
      verificationByAgent: {},
      historyByAgent: {},
    });
  });

  it("should store verification result by agent ID", () => {
    const store = useRerankerVerificationStore.getState();

    store.setVerification("agent-1", verification);

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toEqual(verification);
  });

  it("should maintain verification across multiple agents", () => {
    const store = useRerankerVerificationStore.getState();
    const second = {
      ...verification,
      configKey: JSON.stringify(["https://other/v1", "", "m", "5"]),
      latency: 90,
      precision: 0,
      correctCount: 0,
    };

    store.setVerification("agent-1", verification);
    store.setVerification("agent-2", second);

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toEqual(verification);
    expect(state.verificationByAgent["agent-2"]).toEqual(second);
  });

  it("clears verification for a specific agent while preserving its history", () => {
    const store = useRerankerVerificationStore.getState();

    store.setVerification("agent-1", verification);
    store.setVerification("agent-2", verification);
    store.setHistory("agent-1", configKey, [historyRecord], fingerprintA);

    store.clearVerification("agent-1");

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toBeUndefined();
    expect(state.historyByAgent["agent-1"]?.[configKey]).toEqual({
      configKey,
      fingerprint: fingerprintA,
      records: [historyRecord],
    });
    expect(state.verificationByAgent["agent-2"]).toEqual(verification);
  });

  it("should not fail when clearing non-existent agent verification", () => {
    const store = useRerankerVerificationStore.getState();

    expect(() => {
      store.clearVerification("non-existent-agent");
    }).not.toThrow();
  });

  it("stores history separately from the verification verdict", () => {
    const store = useRerankerVerificationStore.getState();

    store.setHistory("agent-1", configKey, [historyRecord], fingerprintA);

    const state = useRerankerVerificationStore.getState();
    // History loading must never manufacture a verified result.
    expect(state.verificationByAgent["agent-1"]).toBeUndefined();
    expect(state.historyByAgent["agent-1"]?.[configKey]).toEqual({
      configKey,
      fingerprint: fingerprintA,
      records: [historyRecord],
    });
  });

  it("scopes history by service configKey within the same agent", () => {
    const store = useRerankerVerificationStore.getState();
    const otherRecord = {
      ...historyRecord,
      ts: 1_700_000_005_000,
      precision: 0.4,
    };

    store.setHistory("agent-1", configKey, [historyRecord], fingerprintA);
    store.setHistory("agent-1", otherConfigKey, [otherRecord], fingerprintB);

    const agentHistory =
      useRerankerVerificationStore.getState().historyByAgent["agent-1"];
    expect(agentHistory?.[configKey]?.records).toEqual([historyRecord]);
    expect(agentHistory?.[configKey]?.fingerprint).toBe(fingerprintA);
    expect(agentHistory?.[otherConfigKey]?.records).toEqual([otherRecord]);
    expect(agentHistory?.[otherConfigKey]?.fingerprint).toBe(fingerprintB);
  });

  it("refreshing history keeps the manual verdict untouched", () => {
    const store = useRerankerVerificationStore.getState();

    store.setVerification("agent-1", verification);
    store.setHistory("agent-1", configKey, [historyRecord], fingerprintA);

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toEqual(verification);
  });

  it("should update existing verification for same agent", () => {
    const store = useRerankerVerificationStore.getState();
    const updated = {
      ...verification,
      configKey: JSON.stringify(["https://changed/v1", "", "m", "10"]),
      latency: 410,
      precision: null,
      correctCount: 0,
      total: 0,
    };

    store.setVerification("agent-1", verification);
    store.setVerification("agent-1", updated);

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toEqual(updated);
    expect(Object.keys(state.verificationByAgent)).toHaveLength(1);
  });
});
