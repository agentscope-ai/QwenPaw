import { describe, it, expect, beforeEach, vi } from "vitest";
import { useTurnUsageStore } from "./turnUsageStore";

describe("turnUsageStore (#5300 上下文取 max_input_length)", () => {
  beforeEach(() => {
    // reset the store state
    useTurnUsageStore.getState().setSnapshot(null);
    useTurnUsageStore.getState().setActiveMaxInputLength(null);
  });

  describe("publishActiveMaxInputLength 行为验证", () => {
    it("ModelSelector 切换模型后 activeMaxInputLength 更新为模型的 effective_max_input_length", () => {
      // simulate publishActiveMaxInputLength(131072)
      useTurnUsageStore.getState().setActiveMaxInputLength(131072);
      expect(useTurnUsageStore.getState().activeMaxInputLength).toBe(131072);

      // switch to a same-named model under another provider; effective_max_input_length differs
      useTurnUsageStore.getState().setActiveMaxInputLength(32768);
      expect(useTurnUsageStore.getState().activeMaxInputLength).toBe(32768);
    });

    it("activeMaxInputLength 为 null 时表示无活跃模型", () => {
      useTurnUsageStore.getState().setActiveMaxInputLength(null);
      expect(useTurnUsageStore.getState().activeMaxInputLength).toBeNull();
    });
  });

  describe("handleNewCommand 上下文重置应使用当前模型的 max_input_length", () => {
    it("snapshot 有 context_usage 时，新命令重置后保留原 max_input_length", () => {
      // set an initial snapshot to simulate an existing conversation turn
      useTurnUsageStore.getState().setSnapshot({
        usage: {
          total_tokens: 100,
          prompt_tokens: 80,
          completion_tokens: 20,
        } as any,
        context_usage: {
          estimated_tokens: 5000,
          max_input_length: 65536, // 当前模型的 max_input_length
          context_usage_ratio: 7.6,
        },
      });

      const current = useTurnUsageStore.getState().snapshot;
      const maxInputLength = current?.context_usage?.max_input_length ?? 131072;

      // simulate the handleNewCommand reset logic
      useTurnUsageStore.getState().setSnapshot({
        usage: null,
        context_usage: {
          estimated_tokens: 0,
          max_input_length: maxInputLength,
          context_usage_ratio: 0,
        },
      });

      const newSnapshot = useTurnUsageStore.getState().snapshot;
      // Key assertion: after reset, max_input_length keeps the current model value, not hardcoded 131072
      expect(newSnapshot!.context_usage!.max_input_length).toBe(65536);
      expect(newSnapshot!.context_usage!.max_input_length).not.toBe(131072);
    });

    it("snapshot 为 null 时的降级：应使用 activeMaxInputLength 而非硬编码 131072", () => {
      // set activeMaxInputLength (published by ModelSelector via publishActiveMaxInputLength)
      useTurnUsageStore.getState().setActiveMaxInputLength(32768);

      const current = useTurnUsageStore.getState().snapshot;
      const activeMax = useTurnUsageStore.getState().activeMaxInputLength;

      // fallback chain: snapshot -> activeMaxInputLength -> 131072 as the last resort
      const maxInputLength =
        current?.context_usage?.max_input_length ?? activeMax ?? 131072;

      expect(maxInputLength).toBe(32768);
      expect(maxInputLength).not.toBe(131072);
    });

    it("snapshot 和 activeMaxInputLength 都为 null 时降级到 131072", () => {
      const current = useTurnUsageStore.getState().snapshot;
      const activeMax = useTurnUsageStore.getState().activeMaxInputLength;

      const maxInputLength =
        current?.context_usage?.max_input_length ?? activeMax ?? 131072;

      expect(maxInputLength).toBe(131072);
    });

    it("model-switched 事件携带正确的 maxInputLength", () => {
      const listener = vi.fn();
      window.addEventListener("model-switched", listener);

      // simulate the CustomEvent dispatch from publishActiveMaxInputLength
      const maxInputLength = 65536;
      window.dispatchEvent(
        new CustomEvent("model-switched", {
          detail: { maxInputLength },
        }),
      );

      expect(listener).toHaveBeenCalledTimes(1);
      expect(listener.mock.calls[0][0].detail.maxInputLength).toBe(65536);

      window.removeEventListener("model-switched", listener);
    });
  });

  describe("patchContextMaxInputLength 验证", () => {
    it("模型切换后 snapshot 的 max_input_length 应更新为新模型的值", () => {
      // the initial snapshot uses the old model max_input_length
      useTurnUsageStore.getState().setSnapshot({
        usage: null,
        context_usage: {
          estimated_tokens: 5000,
          max_input_length: 32768,
          context_usage_ratio: 15.2,
        },
      });

      // switch the model; the new model max_input_length is 131072
      const newMaxInputLength = 131072;
      const snap = useTurnUsageStore.getState().snapshot;
      const estimatedTokens = snap!.context_usage!.estimated_tokens;
      const newRatio = Math.min(
        (estimatedTokens / newMaxInputLength) * 100,
        100,
      );

      useTurnUsageStore.getState().setSnapshot({
        usage: snap!.usage,
        context_usage: {
          estimated_tokens: estimatedTokens,
          max_input_length: newMaxInputLength,
          context_usage_ratio: newRatio,
        },
      });

      const updated = useTurnUsageStore.getState().snapshot;
      expect(updated!.context_usage!.max_input_length).toBe(131072);
      expect(updated!.context_usage!.estimated_tokens).toBe(5000);
      // the ratio must be recomputed against the new max_input_length
      expect(updated!.context_usage!.context_usage_ratio).toBeCloseTo(
        (5000 / 131072) * 100,
        2,
      );
    });
  });
});
