import { create } from "zustand";

import type { MentionInputDraft } from "@/components/agent/MentionInput";

export interface SelectionAttachment {
  text: string;
  ref: string | null;
  field: string | null;
  /** Exact RFC 6901 pointer to the canonical project.json value, if any. */
  path?: string | null;
  start: number;
  end: number;
  label: string;
  /** Timeline selections use ticks; text selections omit these fields. */
  kind?: "text" | "timeline_point" | "timeline_range";
  timelineId?: string;
  startTick?: number;
  endTick?: number;
  elementIds?: string[];
}

export type AgentDockTab = "conversation" | "activity";

export type WorkspaceSidebarTab = "assistant" | "episodes";

interface AgentDockUiState {
  open: boolean;
  tab: AgentDockTab;
  /** 创作助手/剧集列表 tab —— 跨页面保持用户的上一次选择。 */
  sidebarTab: WorkspaceSidebarTab;
  width: number;
  height: number;
  /** User-dragged height of the creation overview; null keeps the automatic cap. */
  overviewHeight: number | null;
  /** User-dragged height of the inline decision tray; null keeps the automatic cap. */
  decisionTrayHeight: number | null;
  runFilter: string;
  draft: string;
  /**
   * Unsent composer drafts keyed by the Project that produced them. Live
   * typing never reaches the store — that re-rendered the whole dock per
   * keystroke — but folding, unmounting, or switching Projects used to eat an
   * unsent instruction. Keying by Project lets A and B each keep their own
   * draft across a round trip, and this map deliberately survives `reset()`:
   * the layout resets the dock on every Project switch, so clearing here would
   * erase the draft just parked by the unmounting editor.
   */
  unsentDrafts: Record<string, MentionInputDraft>;
  selection: SelectionAttachment | null;
  allowExpandDetails: boolean;
  /**
   * Collapse preference of the inline decision tray; a new blocking item
   * (production confirmation) forces it open.
   */
  decisionTrayCollapsed: boolean;
  setOpen: (open: boolean) => void;
  setTab: (tab: AgentDockTab) => void;
  setSidebarTab: (tab: WorkspaceSidebarTab) => void;
  setSize: (width: number, height: number) => void;
  setOverviewHeight: (height: number | null) => void;
  setDecisionTrayHeight: (height: number | null) => void;
  setRunFilter: (filter: string) => void;
  setDraft: (draft: string) => void;
  /** Stashes (or, with null/empty, drops) one Project's unsent draft. */
  parkUnsentDraft: (
    projectId: string,
    content: MentionInputDraft | null,
  ) => void;
  /** Drops one Project's stashed draft without restoring it. */
  clearUnsentDraft: (projectId: string) => void;
  /** Drops every stashed draft; test isolation only. */
  clearUnsentDrafts: () => void;
  setSelection: (selection: SelectionAttachment | null) => void;
  setAllowExpandDetails: (allow: boolean) => void;
  setDecisionTrayCollapsed: (collapsed: boolean) => void;
  reset: () => void;
}

export const useAgentDockUiStore = create<AgentDockUiState>((set) => ({
  open: true,
  tab: "conversation",
  sidebarTab: "assistant",
  width: 340,
  height: 620,
  overviewHeight: null,
  decisionTrayHeight: null,
  runFilter: "all",
  draft: "",
  unsentDrafts: {},
  selection: null,
  allowExpandDetails: false,
  decisionTrayCollapsed: false,
  setOpen: (open) => set({ open }),
  setTab: (tab) => set({ tab, open: true }),
  setSidebarTab: (sidebarTab) => set({ sidebarTab }),
  setSize: (width, height) =>
    // Floor must match AgentDock's DOCK_MIN_WIDTH so users can actually
    // narrow the dock down to 240px on tight windows.
    set({ width: Math.max(240, width), height: Math.max(320, height) }),
  setOverviewHeight: (overviewHeight) => set({ overviewHeight }),
  setDecisionTrayHeight: (decisionTrayHeight) => set({ decisionTrayHeight }),
  setRunFilter: (runFilter) => set({ runFilter }),
  setDraft: (draft) => set({ draft }),
  parkUnsentDraft: (projectId, content) =>
    set((state) => {
      const parked = state.unsentDrafts[projectId];
      if (!content || !content.length) {
        if (!parked) return state;
        const unsentDrafts = { ...state.unsentDrafts };
        delete unsentDrafts[projectId];
        return { unsentDrafts };
      }
      return {
        unsentDrafts: { ...state.unsentDrafts, [projectId]: content },
      };
    }),
  clearUnsentDraft: (projectId) =>
    set((state) => {
      if (!(projectId in state.unsentDrafts)) return state;
      const unsentDrafts = { ...state.unsentDrafts };
      delete unsentDrafts[projectId];
      return { unsentDrafts };
    }),
  clearUnsentDrafts: () =>
    set((state) =>
      Object.keys(state.unsentDrafts).length ? { unsentDrafts: {} } : state,
    ),
  setSelection: (selection) =>
    set({ selection, tab: "conversation", open: true }),
  setAllowExpandDetails: (allowExpandDetails) => set({ allowExpandDetails }),
  setDecisionTrayCollapsed: (decisionTrayCollapsed) =>
    set({ decisionTrayCollapsed }),
  reset: () =>
    set({
      open: true,
      tab: "conversation",
      width: 340,
      height: 620,
      overviewHeight: null,
      decisionTrayHeight: null,
      runFilter: "all",
      draft: "",
      // `unsentDrafts` intentionally survives: the layout resets the dock on
      // every Project switch, and that map is the hand-off point for drafts
      // that must survive the trip. Tests call `clearUnsentDrafts`.
      selection: null,
      allowExpandDetails: false,
      decisionTrayCollapsed: false,
    }),
}));
