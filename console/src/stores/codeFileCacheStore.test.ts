import { beforeEach, describe, expect, it } from "vitest";
import { useCodeFileCacheStore } from "./codeFileCacheStore";

beforeEach(() => {
  useCodeFileCacheStore.getState().clear();
});

describe("codeFileCacheStore", () => {
  describe("get/set", () => {
    it("returns the stored entry after set", () => {
      const store = useCodeFileCacheStore.getState();
      store.set("foo.ts", "content", "etag-1");
      const entry = store.get("foo.ts");
      expect(entry).toBeDefined();
      expect(entry!.content).toBe("content");
      expect(entry!.etag).toBe("etag-1");
      expect(typeof entry!.touchedAt).toBe("number");
    });

    it("returns undefined for a key that was never set", () => {
      const store = useCodeFileCacheStore.getState();
      expect(store.get("nonexistent.ts")).toBeUndefined();
    });
  });

  describe("invalidate", () => {
    it("removes a previously set entry", () => {
      const store = useCodeFileCacheStore.getState();
      store.set("a.ts", "hello", null);
      store.invalidate("a.ts");
      expect(store.get("a.ts")).toBeUndefined();
    });

    it("does not throw when invalidating a key that does not exist", () => {
      const store = useCodeFileCacheStore.getState();
      expect(() => store.invalidate("nonexistent.ts")).not.toThrow();
    });
  });

  describe("clear", () => {
    it("empties all entries", () => {
      const store = useCodeFileCacheStore.getState();
      store.set("a.ts", "a", null);
      store.set("b.ts", "b", "etag-b");
      store.set("c.ts", "c", "etag-c");
      store.clear();
      expect(useCodeFileCacheStore.getState().entries.size).toBe(0);
    });
  });

  describe("LRU eviction", () => {
    it("keeps at most MAX_ENTRIES (50) entries after 51 insertions", () => {
      const store = useCodeFileCacheStore.getState();
      for (let i = 0; i <= 50; i++) {
        store.set(`file-${i}.ts`, `content-${i}`, null);
      }
      expect(useCodeFileCacheStore.getState().entries.size).toBe(50);
    });

    it("evicts the oldest entry (file-0.ts) when the 51st file is inserted", () => {
      const store = useCodeFileCacheStore.getState();
      // Insert 50 files (fills the cache to MAX_ENTRIES)
      for (let i = 0; i < 50; i++) {
        store.set(`file-${i}.ts`, `content-${i}`, null);
      }
      // Insert one more to trigger eviction
      store.set("file-50.ts", "content-50", null);
      const entries = useCodeFileCacheStore.getState().entries;
      expect(entries.has("file-0.ts")).toBe(false);
      expect(entries.has("file-50.ts")).toBe(true);
    });
  });
});
