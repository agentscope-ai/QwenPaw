import { describe, expect, it, vi } from "vitest";
import {
  isChunkLoadError,
  loadWithChunkRecovery,
} from "@/lib/lazyWithChunkRecovery";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => void values.set(key, value),
    removeItem: (key: string) => void values.delete(key),
  };
}

describe("lazy route chunk recovery", () => {
  it("recognizes browser dynamic import failures", () => {
    expect(
      isChunkLoadError(
        new TypeError("Failed to fetch dynamically imported module: /old.js"),
      ),
    ).toBe(true);
    expect(
      isChunkLoadError(
        new TypeError("error loading dynamically imported module"),
      ),
    ).toBe(true);
    expect(
      isChunkLoadError(new TypeError("Importing a module script failed.")),
    ).toBe(true);
    expect(isChunkLoadError(new Error("API request failed"))).toBe(false);
  });

  it("reloads only once for a stale chunk and clears the guard after success", async () => {
    const storage = memoryStorage();
    const reload = vi.fn();
    const failure = new TypeError(
      "Failed to fetch dynamically imported module: /old.js",
    );

    await expect(
      loadWithChunkRecovery(() => Promise.reject(failure), { storage, reload }),
    ).rejects.toBe(failure);
    await expect(
      loadWithChunkRecovery(() => Promise.reject(failure), { storage, reload }),
    ).rejects.toBe(failure);
    expect(reload).toHaveBeenCalledTimes(1);

    await expect(
      loadWithChunkRecovery(() => Promise.resolve({ default: "loaded" }), {
        storage,
        reload,
      }),
    ).resolves.toEqual({ default: "loaded" });
    await expect(
      loadWithChunkRecovery(() => Promise.reject(failure), { storage, reload }),
    ).rejects.toBe(failure);
    expect(reload).toHaveBeenCalledTimes(2);

    // Unrelated module errors never trigger a reload.
    const unrelated = new Error("module executed but failed");
    await expect(
      loadWithChunkRecovery(() => Promise.reject(unrelated), {
        storage: memoryStorage(),
        reload,
      }),
    ).rejects.toBe(unrelated);
    expect(reload).toHaveBeenCalledTimes(2);
  });
});
