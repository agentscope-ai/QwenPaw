import { describe, it, expect, beforeEach } from "vitest";
import { useEmbeddingVerificationStore } from "./embeddingVerificationStore";

describe("embeddingVerificationStore", () => {
  beforeEach(() => {
    // Reset store state before each test
    useEmbeddingVerificationStore.setState({
      verificationByAgent: {},
    });
  });

  describe("GH#7226 - Embedding verification state persistence", () => {
    it("should store verification result by agent ID", () => {
      const store = useEmbeddingVerificationStore.getState();

      const verification = {
        fingerprint: "openai-text-embedding-3-small-1536",
        dimensions: 1536,
        latency: 245,
        verifiedAt: Date.now(),
      };

      store.setVerification("agent-1", verification);

      const state = useEmbeddingVerificationStore.getState();
      expect(state.verificationByAgent["agent-1"]).toEqual(verification);
    });

    it("should maintain verification across multiple agents", () => {
      const store = useEmbeddingVerificationStore.getState();

      const verification1 = {
        fingerprint: "openai-text-embedding-3-small-1536",
        dimensions: 1536,
        latency: 245,
        verifiedAt: Date.now(),
      };

      const verification2 = {
        fingerprint: "dashscope-text-embedding-v2-1024",
        dimensions: 1024,
        latency: 180,
        verifiedAt: Date.now(),
      };

      store.setVerification("agent-1", verification1);
      store.setVerification("agent-2", verification2);

      const state = useEmbeddingVerificationStore.getState();
      expect(state.verificationByAgent["agent-1"]).toEqual(verification1);
      expect(state.verificationByAgent["agent-2"]).toEqual(verification2);
    });

    it("should clear verification for specific agent", () => {
      const store = useEmbeddingVerificationStore.getState();

      const verification1 = {
        fingerprint: "openai-text-embedding-3-small-1536",
        dimensions: 1536,
        latency: 245,
        verifiedAt: Date.now(),
      };

      const verification2 = {
        fingerprint: "dashscope-text-embedding-v2-1024",
        dimensions: 1024,
        latency: 180,
        verifiedAt: Date.now(),
      };

      store.setVerification("agent-1", verification1);
      store.setVerification("agent-2", verification2);

      store.clearVerification("agent-1");

      const state = useEmbeddingVerificationStore.getState();
      expect(state.verificationByAgent["agent-1"]).toBeUndefined();
      expect(state.verificationByAgent["agent-2"]).toEqual(verification2);
    });

    it("should not fail when clearing non-existent agent verification", () => {
      const store = useEmbeddingVerificationStore.getState();

      expect(() => {
        store.clearVerification("non-existent-agent");
      }).not.toThrow();
    });

    it("should update existing verification for same agent", () => {
      const store = useEmbeddingVerificationStore.getState();

      const verification1 = {
        fingerprint: "openai-text-embedding-3-small-1536",
        dimensions: 1536,
        latency: 245,
        verifiedAt: Date.now(),
      };

      const verification2 = {
        fingerprint: "openai-text-embedding-3-large-3072",
        dimensions: 3072,
        latency: 320,
        verifiedAt: Date.now(),
      };

      store.setVerification("agent-1", verification1);
      store.setVerification("agent-1", verification2);

      const state = useEmbeddingVerificationStore.getState();
      expect(state.verificationByAgent["agent-1"]).toEqual(verification2);
      expect(Object.keys(state.verificationByAgent)).toHaveLength(1);
    });

    it("should preserve verification state when store is accessed multiple times", () => {
      const store = useEmbeddingVerificationStore.getState();

      const verification = {
        fingerprint: "openai-text-embedding-3-small-1536",
        dimensions: 1536,
        latency: 245,
        verifiedAt: Date.now(),
      };

      store.setVerification("agent-1", verification);

      // Separate getState() reads must all observe the stored entry: the
      // store is the only place this result lives, so any consumer reading
      // it later has to see the same value.
      const state1 = useEmbeddingVerificationStore.getState();
      const state2 = useEmbeddingVerificationStore.getState();
      const state3 = useEmbeddingVerificationStore.getState();

      expect(state1.verificationByAgent["agent-1"]).toEqual(verification);
      expect(state2.verificationByAgent["agent-1"]).toEqual(verification);
      expect(state3.verificationByAgent["agent-1"]).toEqual(verification);
    });
  });
});
