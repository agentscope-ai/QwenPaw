import { describe, expect, it, vi } from "vitest";
import { waitForPluginReady } from "./usePluginLoader";

describe("waitForPluginReady", () => {
  it("waits for a plugin readiness promise", async () => {
    let resolveReady: (() => void) | undefined;
    const ready = new Promise<void>((resolve) => {
      resolveReady = resolve;
    });
    const completed = vi.fn();

    const waiting = waitForPluginReady({ default: ready }).then(completed);
    await Promise.resolve();
    expect(completed).not.toHaveBeenCalled();

    resolveReady?.();
    await waiting;
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it("accepts plugins without an asynchronous initializer", async () => {
    await expect(waitForPluginReady({})).resolves.toBeUndefined();
  });
});
