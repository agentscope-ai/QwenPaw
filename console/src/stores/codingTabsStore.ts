/**
 * Per-agent persistence for Coding Mode editor tabs and pending diffs.
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
import { persist } from "zustand/middleware";
import { useAgentStore } from "./agentStore";
import type { WorkspaceRoot } from "../features/files-workspace/types";

export const ORIGINAL_DIFF_SIZE_LIMIT = 256 * 1024;

export interface EditorTab {
  /** Internal stable identity used by the tab/diff stores. */
  path: string;
  /** User-facing and filesystem path. Never contains an internal source key. */
  displayPath?: string;
  content: string;
  dirty: boolean;
  source?: "workspace" | "attachment" | "profile" | "memory";
  workspaceRoot?: WorkspaceRoot;
  artifactUrl?: string;
  previewKind?: "text" | "image" | "pdf" | "csv" | "binary";
  readOnly?: boolean;
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
  setTabDirty: (agentId: string, path: string, dirty: boolean) => void;

  clearAgent: (agentId: string) => void;

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
      name: "qwenpaw-coding-tabs",
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

export function useCurrentTabs(): EditorTab[] {
  const { selectedAgent } = useAgentStore();
  return useCodingTabsStore((s) => s.tabsByAgent[selectedAgent] ?? EMPTY_TABS);
}

export function useCurrentActiveTabPath(): string {
  const { selectedAgent } = useAgentStore();
  return useCodingTabsStore((s) => s.activeTabByAgent[selectedAgent] ?? "");
}

export function useCurrentDiffs(): Record<string, PendingDiff> {
  const { selectedAgent } = useAgentStore();
  return useCodingTabsStore(
    (s) => s.diffsByAgent[selectedAgent] ?? EMPTY_DIFFS,
  );
}
