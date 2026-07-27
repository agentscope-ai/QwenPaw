/**
 * Tests for the warm-up queue used by registerHostModulesDynamic.
 *
 * Warm-up must run imports in small sequential batches (yielding to an
 * idle slot between batches) instead of firing all ~260 at once, and a
 * failed task must not abort the rest of the queue.
 */
import { describe, expect, it, vi } from "vitest";
import { runWarmupQueue } from "./dynamicModuleRegistry";

describe("runWarmupQueue", () => {
  it("runs at most batchSize tasks concurrently", async () => {
    let running = 0;
    let maxRunning = 0;
    const tasks = Array.from({ length: 10 }, () => async () => {
      running++;
      maxRunning = Math.max(maxRunning, running);
      await new Promise((r) => setTimeout(r, 1));
      running--;
      return true;
    });

    const results = await runWarmupQueue(tasks, 4, async () => {});

    expect(results).toHaveLength(10);
    expect(maxRunning).toBeLessThanOrEqual(4);
  });

  it("waits for an idle slot before each batch", async () => {
    const waitSlot = vi.fn(async () => {});
    const tasks = Array.from({ length: 9 }, () => async () => true);

    await runWarmupQueue(tasks, 4, waitSlot);

    // 9 tasks / batch of 4 → 3 batches → 3 idle waits.
    expect(waitSlot).toHaveBeenCalledTimes(3);
  });

  it("keeps processing after a task rejects", async () => {
    const tasks = [
      async () => "ok-1",
      async () => {
        throw new Error("boom");
      },
      async () => "ok-2",
    ];

    const results = await runWarmupQueue(tasks, 2, async () => {});

    expect(results.map((r) => r.status)).toEqual([
      "fulfilled",
      "rejected",
      "fulfilled",
    ]);
  });
});
