import { describe, it, expect, beforeEach } from "vitest";
import { useRerankerVerificationStore } from "./rerankerVerificationStore";

describe("rerankerVerificationStore", () => {
  beforeEach(() => {
    // Reset store state before each test
    useRerankerVerificationStore.setState({
      verificationByAgent: {},
    });
  });

  it("should store verification result by agent ID", () => {
    const store = useRerankerVerificationStore.getState();

    const verification = {
      fingerprint: "https://api.siliconflow.cn/v1-key-model-10",
      latency: 320,
      precision: 1,
      correctCount: 3,
      total: 3,
      history: [],
      verifiedAt: Date.now(),
    };

    store.setVerification("agent-1", verification);

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toEqual(verification);
  });

  it("should maintain verification across multiple agents", () => {
    const store = useRerankerVerificationStore.getState();

    const verification1 = {
      fingerprint: "https://api.siliconflow.cn/v1-key-model-10",
      latency: 320,
      precision: 1,
      correctCount: 3,
      total: 3,
      history: [],
      verifiedAt: Date.now(),
    };
    const verification2 = {
      fingerprint: "http://localhost:8000-key-model-5",
      latency: 90,
      precision: 0,
      correctCount: 0,
      total: 3,
      history: [],
      verifiedAt: Date.now(),
    };

    store.setVerification("agent-1", verification1);
    store.setVerification("agent-2", verification2);

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toEqual(verification1);
    expect(state.verificationByAgent["agent-2"]).toEqual(verification2);
  });

  it("should clear verification for specific agent", () => {
    const store = useRerankerVerificationStore.getState();

    const verification1 = {
      fingerprint: "https://api.siliconflow.cn/v1-key-model-10",
      latency: 320,
      precision: 1,
      correctCount: 3,
      total: 3,
      history: [],
      verifiedAt: Date.now(),
    };
    const verification2 = {
      fingerprint: "http://localhost:8000-key-model-5",
      latency: 90,
      precision: 0,
      correctCount: 0,
      total: 3,
      history: [],
      verifiedAt: Date.now(),
    };

    store.setVerification("agent-1", verification1);
    store.setVerification("agent-2", verification2);

    store.clearVerification("agent-1");

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toBeUndefined();
    expect(state.verificationByAgent["agent-2"]).toEqual(verification2);
  });

  it("should not fail when clearing non-existent agent verification", () => {
    const store = useRerankerVerificationStore.getState();

    expect(() => {
      store.clearVerification("non-existent-agent");
    }).not.toThrow();
  });

  it("should update existing verification for same agent", () => {
    const store = useRerankerVerificationStore.getState();

    const verification1 = {
      fingerprint: "https://api.siliconflow.cn/v1-key-model-10",
      latency: 320,
      precision: 1,
      correctCount: 3,
      total: 3,
      history: [],
      verifiedAt: Date.now(),
    };
    const verification2 = {
      fingerprint: "https://api.siliconflow.cn/v1-key-other-model-10",
      latency: 410,
      precision: null,
      correctCount: 0,
      total: 0,
      history: [],
      verifiedAt: Date.now(),
    };

    store.setVerification("agent-1", verification1);
    store.setVerification("agent-1", verification2);

    const state = useRerankerVerificationStore.getState();
    expect(state.verificationByAgent["agent-1"]).toEqual(verification2);
    expect(Object.keys(state.verificationByAgent)).toHaveLength(1);
  });
});
