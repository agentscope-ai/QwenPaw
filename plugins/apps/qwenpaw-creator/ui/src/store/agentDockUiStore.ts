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
  runFilter: string;
  draft: string;
  /**
   * The input's structured content (text segments, mention pills, selection
   * attachments) stashed when the dock folds or unmounts. Live typing never
   * reaches the store -- that re-rendered the whole dock per keystroke -- but
   * unmounting used to eat an unsent instruction with it (review #243).
   *
   * Tagged with the Project that produced it: navigation between Projects
   * can unmount and remount the same dock, and an untagged stash would
   * restore Project A's half-typed instruction into Project B's composer
   * -- where a send would deliver it to the wrong session entirely
   * (review #243 blocking #5). Consumers must compare
   * ``unsentDraft.projectId`` against the current route id before applying.
   */
  unsentDraft: { projectId: string; content: MentionInputDraft } | null;
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
  setRunFilter: (filter: string) => void;
  setDraft: (draft: string) => void;
  setUnsentDraft: (
    draft: { projectId: string; content: MentionInputDraft } | null,
  ) => void;
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
  runFilter: "all",
  draft: "",
  unsentDraft: null,
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
  setRunFilter: (runFilter) => set({ runFilter }),
  setDraft: (draft) => set({ draft }),
  setUnsentDraft: (unsentDraft) => set({ unsentDraft }),
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
      runFilter: "all",
      draft: "",
      unsentDraft: null,
      selection: null,
      allowExpandDetails: false,
      decisionTrayCollapsed: false,
    }),
}));
