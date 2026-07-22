/**
 * In-memory cache for Coding Mode file contents.
 *
 *   • Keyed by relative file path (the same path the backend uses).
 *   • LRU-bounded so a marathon session doesn't bloat heap.
 *   • NOT persisted — file contents must never spill to localStorage.
 *   • Invalidated by the SSE workspace watcher when the file is modified
 *     or deleted; tab switches in the IDE then read straight from cache.
 *
 * Layout decision: ETag is stored alongside content so we can send
 * `If-None-Match` and short-circuit to 304 even after a hard refresh
 * (when the in-memory cache is gone but the browser HTTP cache may still
 * be primed). For pure tab-switch reads we just return content directly.
 */
import { create } from "zustand";

const MAX_ENTRIES = 50;

interface CacheEntry {
  content: string;
  etag: string | null;
  /** Monotonic counter — last access wins on eviction */
  touchedAt: number;
}

interface CodeFileCacheState {
  entries: Map<string, CacheEntry>;
  counter: number;

  get: (path: string) => CacheEntry | undefined;
  set: (path: string, content: string, etag: string | null) => void;
  invalidate: (path: string) => void;
  clear: () => void;
}

export const useCodeFileCacheStore = create<CodeFileCacheState>((set, get) => ({
  entries: new Map(),
  counter: 0,

  get: (path) => {
    const entry = get().entries.get(path);
    if (!entry) return undefined;
    // Bump touchedAt on read so LRU reflects access patterns
    entry.touchedAt = ++get().counter;
    return entry;
  },

  set: (path, content, etag) => {
    set((state) => {
      const next = new Map(state.entries);
      const newCounter = state.counter + 1;
      next.set(path, { content, etag, touchedAt: newCounter });

      // LRU eviction
      if (next.size > MAX_ENTRIES) {
        let oldestKey: string | null = null;
        let oldestTime = Infinity;
        for (const [k, v] of next) {
          if (v.touchedAt < oldestTime) {
            oldestTime = v.touchedAt;
            oldestKey = k;
          }
        }
        if (oldestKey !== null) next.delete(oldestKey);
      }

      return { entries: next, counter: newCounter };
    });
  },

  invalidate: (path) => {
    set((state) => {
      if (!state.entries.has(path)) return state;
      const next = new Map(state.entries);
      next.delete(path);
      return { entries: next };
    });
  },

  clear: () => set({ entries: new Map(), counter: 0 }),
}));
