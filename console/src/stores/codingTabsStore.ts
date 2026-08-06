/**
 * Per-scope persistence for Files workspace tabs and pending diffs.
 *
 * Persists to localStorage so the IDE survives a page reload and an
 * agent-switch round trip. To stay under the localStorage quota:
 *
 *   • File contents are NOT persisted — the path list is, and content
 *     is re-fetched via workspaceApi.loadCodeFile on hydrate (which
 *     hits the in-memory codeFileCacheStore + browser HTTP cache).
 *   • For pending diffs, only the `original` (pre-diff baseline) is
 *     persisted, capped at ORIGINAL_DIFF_SIZE_LIMIT. Above the cap,
 *     the diff stays in memory only and is dropped on reload.
 *   • The `modified` side of a diff is null after rehydrate; the
 *     consumer fetches the disk content on mount to fill it in.
 */
import { create } from "zustand";
import {
  createJSONStorage,
  persist,
  type StateStorage,
} from "zustand/middleware";
import type {
  FileSource,
  WorkspaceRoot,
} from "../features/files-workspace/types";

export const ORIGINAL_DIFF_SIZE_LIMIT = 256 * 1024;
export const AGENT_FILES_TABS_STORAGE_KEY = "qwenpaw-agent-files-tabs";
export const SESSION_FILES_TABS_STORAGE_KEY = "qwenpaw-session-files-tabs";

export interface EditorTab {
  /** Internal stable identity used by the tab/diff stores. */
  path: string;
  /** User-facing and filesystem path. Never contains an internal source key. */
  displayPath?: string;
  content: string;
  dirty: boolean;
  source?: FileSource;
  workspaceRoot?: WorkspaceRoot;
  artifactUrl?: string;
  previewKind?: "text" | "image" | "pdf" | "csv" | "binary";
  readOnly?: boolean;
  /** Current disk version. Kept in memory only and refreshed after loading. */
  etag?: string;
}

export interface PendingDiff {
  original: string;
  /** null after rehydrate, populated by consumer's hydrate effect. */
  modified: string | null;
}

interface CodingTabsState {
  tabsByAgent: Record<string, EditorTab[]>;
  activeTabByAgent: Record<string, string>;
  diffsByAgent: Record<string, Record<string, PendingDiff>>;

  openTab: (agentId: string, tab: EditorTab) => void;
  closeTab: (agentId: string, path: string) => void;
  setActiveTab: (agentId: string, path: string) => void;
  setTabContent: (agentId: string, path: string, content: string) => void;
  setTabEtag: (agentId: string, path: string, etag: string) => void;
  setTabDirty: (agentId: string, path: string, dirty: boolean) => void;

  clearAgent: (agentId: string) => void;
  clearProjectTabs: (scopeKey: string) => void;
  migrateScope: (fromScopeKey: string, toScopeKey: string) => void;
  removeScope: (scopeKey: string) => void;

  setDiff: (agentId: string, path: string, diff: PendingDiff) => void;
  removeDiff: (agentId: string, path: string) => void;
  updateDiffModified: (agentId: string, path: string, modified: string) => void;
  updateDiffOriginal: (agentId: string, path: string, original: string) => void;
  resolveDiff: (agentId: string, path: string, content: string) => void;
}

const omitKey = <T extends object>(obj: T, key: string): T => {
  if (!(key in obj)) return obj;
  const next = { ...obj } as Record<string, unknown>;
  delete next[key];
  return next as T;
};

interface PersistedTabsEnvelope {
  state?: {
    tabsByAgent?: Record<string, EditorTab[]>;
    activeTabByAgent?: Record<string, string>;
    diffsByAgent?: Record<string, Record<string, PendingDiff>>;
  };
  version?: number;
}

function filterRecord<T>(
  record: Record<string, T> | undefined,
  prefix: "agent:" | "session:",
): Record<string, T> {
  return Object.fromEntries(
    Object.entries(record ?? {}).filter(([key]) => key.startsWith(prefix)),
  );
}

function scopedEnvelope(
  envelope: PersistedTabsEnvelope,
  prefix: "agent:" | "session:",
): PersistedTabsEnvelope {
  return {
    ...envelope,
    state: {
      tabsByAgent: filterRecord(envelope.state?.tabsByAgent, prefix),
      activeTabByAgent: filterRecord(envelope.state?.activeTabByAgent, prefix),
      diffsByAgent: filterRecord(envelope.state?.diffsByAgent, prefix),
    },
  };
}

/**
 * Zustand sees one store at runtime, while persistence is physically split
 * by ownership. The retired shared key is intentionally never read.
 */
const splitTabsStorage: StateStorage = {
  getItem: () => {
    const agentValue = localStorage.getItem(AGENT_FILES_TABS_STORAGE_KEY);
    const sessionValue = localStorage.getItem(SESSION_FILES_TABS_STORAGE_KEY);
    if (!agentValue && !sessionValue) return null;

    const agentEnvelope = agentValue
      ? (JSON.parse(agentValue) as PersistedTabsEnvelope)
      : {};
    const sessionEnvelope = sessionValue
      ? (JSON.parse(sessionValue) as PersistedTabsEnvelope)
      : {};
    return JSON.stringify({
      ...agentEnvelope,
      ...sessionEnvelope,
      state: {
        tabsByAgent: {
          ...agentEnvelope.state?.tabsByAgent,
          ...sessionEnvelope.state?.tabsByAgent,
        },
        activeTabByAgent: {
          ...agentEnvelope.state?.activeTabByAgent,
          ...sessionEnvelope.state?.activeTabByAgent,
        },
        diffsByAgent: {
          ...agentEnvelope.state?.diffsByAgent,
          ...sessionEnvelope.state?.diffsByAgent,
        },
      },
    } satisfies PersistedTabsEnvelope);
  },
  setItem: (_name, value) => {
    const envelope = JSON.parse(value) as PersistedTabsEnvelope;
    localStorage.setItem(
      AGENT_FILES_TABS_STORAGE_KEY,
      JSON.stringify(scopedEnvelope(envelope, "agent:")),
    );
    localStorage.setItem(
      SESSION_FILES_TABS_STORAGE_KEY,
      JSON.stringify(scopedEnvelope(envelope, "session:")),
    );
  },
  removeItem: () => {
    localStorage.removeItem(AGENT_FILES_TABS_STORAGE_KEY);
    localStorage.removeItem(SESSION_FILES_TABS_STORAGE_KEY);
  },
};

export const useCodingTabsStore = create<CodingTabsState>()(
  persist<CodingTabsState>(
    (set) => ({
      tabsByAgent: {},
      activeTabByAgent: {},
      diffsByAgent: {},

      clearAgent: (agentId) =>
        set((state) => ({
          tabsByAgent: { ...state.tabsByAgent, [agentId]: [] },
          activeTabByAgent: { ...state.activeTabByAgent, [agentId]: "" },
          diffsByAgent: { ...state.diffsByAgent, [agentId]: {} },
        })),

      clearProjectTabs: (scopeKey) =>
        set((state) => {
          const tabs = state.tabsByAgent[scopeKey] ?? [];
          const removedPaths = new Set(
            tabs
              .filter(
                (tab) =>
                  (tab.source ?? "workspace") === "workspace" &&
                  (tab.workspaceRoot ?? "project") === "project",
              )
              .map((tab) => tab.path),
          );
          if (removedPaths.size === 0) return state;
          const nextTabs = tabs.filter((tab) => !removedPaths.has(tab.path));
          const activePath = state.activeTabByAgent[scopeKey] ?? "";
          const diffs = state.diffsByAgent[scopeKey] ?? {};
          return {
            tabsByAgent: {
              ...state.tabsByAgent,
              [scopeKey]: nextTabs,
            },
            activeTabByAgent: {
              ...state.activeTabByAgent,
              [scopeKey]: removedPaths.has(activePath)
                ? nextTabs[0]?.path ?? ""
                : activePath,
            },
            diffsByAgent: {
              ...state.diffsByAgent,
              [scopeKey]: Object.fromEntries(
                Object.entries(diffs).filter(
                  ([path]) => !removedPaths.has(path),
                ),
              ),
            },
          };
        }),

      migrateScope: (fromScopeKey, toScopeKey) =>
        set((state) => {
          if (fromScopeKey === toScopeKey) return state;
          const tabs = state.tabsByAgent[fromScopeKey];
          const activeTab = state.activeTabByAgent[fromScopeKey];
          const diffs = state.diffsByAgent[fromScopeKey];
          if (!tabs && !activeTab && !diffs) return state;
          return {
            tabsByAgent: {
              ...omitKey(state.tabsByAgent, fromScopeKey),
              [toScopeKey]: tabs ?? [],
            },
            activeTabByAgent: {
              ...omitKey(state.activeTabByAgent, fromScopeKey),
              [toScopeKey]: activeTab ?? "",
            },
            diffsByAgent: {
              ...omitKey(state.diffsByAgent, fromScopeKey),
              [toScopeKey]: diffs ?? {},
            },
          };
        }),

      removeScope: (scopeKey) =>
        set((state) => ({
          tabsByAgent: omitKey(state.tabsByAgent, scopeKey),
          activeTabByAgent: omitKey(state.activeTabByAgent, scopeKey),
          diffsByAgent: omitKey(state.diffsByAgent, scopeKey),
        })),

      openTab: (agentId, tab) =>
        set((state) => {
          const existing = state.tabsByAgent[agentId] ?? [];
          if (existing.some((t) => t.path === tab.path)) return state;
          return {
            tabsByAgent: {
              ...state.tabsByAgent,
              [agentId]: [...existing, tab],
            },
          };
        }),

      closeTab: (agentId, path) =>
        set((state) => {
          const tabs = state.tabsByAgent[agentId] ?? [];
          const nextTabs = tabs.filter((t) => t.path !== path);
          const agentDiffs = state.diffsByAgent[agentId] ?? {};
          const nextDiffs =
            path in agentDiffs ? omitKey(agentDiffs, path) : agentDiffs;
          return {
            tabsByAgent: { ...state.tabsByAgent, [agentId]: nextTabs },
            diffsByAgent: { ...state.diffsByAgent, [agentId]: nextDiffs },
          };
        }),

      setActiveTab: (agentId, path) =>
        set((state) => ({
          activeTabByAgent: {
            ...state.activeTabByAgent,
            [agentId]: path,
          },
        })),

      setTabContent: (agentId, path, content) =>
        set((state) => {
          const tabs = state.tabsByAgent[agentId] ?? [];
          if (!tabs.some((t) => t.path === path)) return state;
          return {
            tabsByAgent: {
              ...state.tabsByAgent,
              [agentId]: tabs.map((t) =>
                t.path === path ? { ...t, content } : t,
              ),
            },
          };
        }),

      setTabEtag: (agentId, path, etag) =>
        set((state) => {
          const tabs = state.tabsByAgent[agentId] ?? [];
          if (!tabs.some((t) => t.path === path)) return state;
          return {
            tabsByAgent: {
              ...state.tabsByAgent,
              [agentId]: tabs.map((t) =>
                t.path === path ? { ...t, etag } : t,
              ),
            },
          };
        }),

      setTabDirty: (agentId, path, dirty) =>
        set((state) => {
          const tabs = state.tabsByAgent[agentId] ?? [];
          if (!tabs.some((t) => t.path === path)) return state;
          return {
            tabsByAgent: {
              ...state.tabsByAgent,
              [agentId]: tabs.map((t) =>
                t.path === path ? { ...t, dirty } : t,
              ),
            },
          };
        }),

      setDiff: (agentId, path, diff) =>
        set((state) => ({
          diffsByAgent: {
            ...state.diffsByAgent,
            [agentId]: {
              ...(state.diffsByAgent[agentId] ?? {}),
              [path]: diff,
            },
          },
        })),

      removeDiff: (agentId, path) =>
        set((state) => {
          const agentDiffs = state.diffsByAgent[agentId] ?? {};
          if (!(path in agentDiffs)) return state;
          return {
            diffsByAgent: {
              ...state.diffsByAgent,
              [agentId]: omitKey(agentDiffs, path),
            },
          };
        }),

      updateDiffModified: (agentId, path, modified) =>
        set((state) => {
          const agentDiffs = state.diffsByAgent[agentId] ?? {};
          const existing = agentDiffs[path];
          if (!existing) return state;
          return {
            diffsByAgent: {
              ...state.diffsByAgent,
              [agentId]: {
                ...agentDiffs,
                [path]: { ...existing, modified },
              },
            },
          };
        }),

      updateDiffOriginal: (agentId, path, original) =>
        set((state) => {
          const agentDiffs = state.diffsByAgent[agentId] ?? {};
          const existing = agentDiffs[path];
          if (!existing) return state;
          return {
            diffsByAgent: {
              ...state.diffsByAgent,
              [agentId]: {
                ...agentDiffs,
                [path]: { ...existing, original },
              },
            },
          };
        }),

      resolveDiff: (agentId, path, content) =>
        set((state) => {
          const tabs = state.tabsByAgent[agentId] ?? [];
          const agentDiffs = state.diffsByAgent[agentId] ?? {};
          return {
            tabsByAgent: {
              ...state.tabsByAgent,
              [agentId]: tabs.map((tab) =>
                tab.path === path ? { ...tab, content, dirty: false } : tab,
              ),
            },
            diffsByAgent: {
              ...state.diffsByAgent,
              [agentId]: omitKey(agentDiffs, path),
            },
          };
        }),
    }),
    {
      name: "qwenpaw-split-files-workbench",
      storage: createJSONStorage(() => splitTabsStorage),
      // Persist only the path list (no content/dirty) and small `original`s.
      partialize: ((state: CodingTabsState) => ({
        tabsByAgent: Object.fromEntries(
          Object.entries(state.tabsByAgent).map(([agent, tabs]) => [
            agent,
            tabs.map((t) => ({
              path: t.path,
              displayPath: t.displayPath,
              content: "",
              dirty: false,
              source: t.source,
              workspaceRoot: t.workspaceRoot,
              artifactUrl: t.artifactUrl,
              previewKind: t.previewKind,
              readOnly: t.readOnly,
            })),
          ]),
        ),
        activeTabByAgent: state.activeTabByAgent,
        diffsByAgent: Object.fromEntries(
          Object.entries(state.diffsByAgent).map(([agent, diffs]) => [
            agent,
            Object.fromEntries(
              Object.entries(diffs)
                .filter(
                  ([, d]) => d.original.length <= ORIGINAL_DIFF_SIZE_LIMIT,
                )
                .map(([p, d]) => [p, { original: d.original, modified: null }]),
            ),
          ]),
        ),
      })) as unknown as (state: CodingTabsState) => CodingTabsState,
    },
  ),
);

// Stable empty references — selectors must return the SAME reference when
// the slice is missing, otherwise React will re-render forever.
const EMPTY_TABS: EditorTab[] = [];
const EMPTY_DIFFS: Record<string, PendingDiff> = {};

export function useTabsForScope(scopeKey: string): EditorTab[] {
  return useCodingTabsStore((s) => s.tabsByAgent[scopeKey] ?? EMPTY_TABS);
}

export function useActiveTabPathForScope(scopeKey: string): string {
  return useCodingTabsStore((s) => s.activeTabByAgent[scopeKey] ?? "");
}

export function useDiffsForScope(
  scopeKey: string,
): Record<string, PendingDiff> {
  return useCodingTabsStore((s) => s.diffsByAgent[scopeKey] ?? EMPTY_DIFFS);
}
