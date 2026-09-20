import { create } from "zustand";
import type { ProjectDocument } from "@/contracts/creator";

interface TimelineStore {
  activeTimelineId: string | null;
  compareTimelineId: string | null;
  /** Snapshot picked in the history panel; store-held so background project
      polls (which remount the panel) cannot wipe the user's selection. */
  snapshotSelectedId: string | null;
  setActiveTimelineId: (id: string | null) => void;
  setCompareTimelineId: (id: string | null) => void;
  setSnapshotSelectedId: (id: string | null) => void;
  toggleCompare: (id: string) => void;
  syncTimelines: (project: ProjectDocument) => void;
  reset: () => void;
}

export const useTimelineStore = create<TimelineStore>((set, get) => ({
  activeTimelineId: null,
  compareTimelineId: null,
  snapshotSelectedId: null,

  setActiveTimelineId: (id) => {
    const { compareTimelineId } = get();
    set({
      activeTimelineId: id,
      compareTimelineId: compareTimelineId === id ? null : compareTimelineId,
    });
  },

  setCompareTimelineId: (id) => set({ compareTimelineId: id }),

  setSnapshotSelectedId: (id) => set({ snapshotSelectedId: id }),

  toggleCompare: (id) => {
    const { compareTimelineId } = get();
    set({ compareTimelineId: compareTimelineId === id ? null : id });
  },

  syncTimelines: (project) => {
    const { activeTimelineId, compareTimelineId, snapshotSelectedId } = get();
    const { order, items } = project.timelines;

    const updates: Partial<TimelineStore> = {};

    if (activeTimelineId && !items[activeTimelineId]) {
      updates.activeTimelineId = order[0] ?? null;
    }

    if (compareTimelineId && !items[compareTimelineId]) {
      updates.compareTimelineId = null;
    }

    if (snapshotSelectedId && !items[snapshotSelectedId]) {
      updates.snapshotSelectedId = null;
    }

    if (Object.keys(updates).length > 0) {
      set(updates);
    }
  },

  reset: () =>
    set({
      activeTimelineId: null,
      compareTimelineId: null,
      snapshotSelectedId: null,
    }),
}));
