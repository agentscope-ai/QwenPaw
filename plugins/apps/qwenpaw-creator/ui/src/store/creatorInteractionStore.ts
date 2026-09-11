import { create } from "zustand";
import type { RefSearchItem } from "@/contracts/creator";
import type { SelectionAttachment } from "./agentDockUiStore";

export type CreatorPanel = "plan" | "assets" | "other";

interface CreatorInteractionState {
  panel: CreatorPanel;
  selectedRef: string | null;
  editingField: string | null;
  selection: SelectionAttachment | null;
  extraRefs: RefSearchItem[];

  setPanel: (panel: CreatorPanel) => void;
  select: (ref: string | null) => void;
  setEditingField: (field: string | null) => void;
  setSelection: (selection: SelectionAttachment | null) => void;
  setExtraRefs: (refs: RefSearchItem[]) => void;
  reset: () => void;
}

export const useCreatorInteractionStore = create<CreatorInteractionState>(
  (set) => ({
    panel: "other",
    selectedRef: null,
    editingField: null,
    selection: null,
    extraRefs: [],
    setPanel: (panel) => set({ panel }),
    select: (selectedRef) => set({ selectedRef }),
    setEditingField: (editingField) => set({ editingField }),
    setSelection: (selection) => set({ selection }),
    setExtraRefs: (extraRefs) => set({ extraRefs }),
    reset: () =>
      set({
        panel: "other",
        selectedRef: null,
        editingField: null,
        selection: null,
        extraRefs: [],
      }),
  }),
);
