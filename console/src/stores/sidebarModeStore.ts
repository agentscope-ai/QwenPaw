import { create } from "zustand";

const STORAGE_KEY = "qwenpaw_sidebar_mode";
const FOCUS_ITEMS_STORAGE_KEY = "qwenpaw_sidebar_focus_items_v1";
const HIDDEN_PLUGIN_ITEMS_STORAGE_KEY =
  "qwenpaw_sidebar_hidden_plugin_items_v1";

export const DEFAULT_FOCUS_ITEM_IDS = [
  "core.files",
  "core.cron-jobs",
  "core.marketplace",
];

export type SidebarMode = "simple" | "full";

interface SidebarModeState {
  mode: SidebarMode;
  focusItemIds: string[];
  hiddenPluginItemIds: string[];
  toggleMode: () => void;
  setMode: (mode: SidebarMode) => void;
  setFocusItemIds: (itemIds: string[]) => void;
  setSidebarItemVisible: (itemId: string, visible: boolean) => void;
  resetFocusItemIds: () => void;
}

function loadFocusItemIds(): string[] {
  try {
    const stored = localStorage.getItem(FOCUS_ITEMS_STORAGE_KEY);
    if (!stored) return DEFAULT_FOCUS_ITEM_IDS;
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return DEFAULT_FOCUS_ITEM_IDS;
    return parsed.filter(
      (itemId): itemId is string =>
        typeof itemId === "string" && itemId !== "core.inbox",
    );
  } catch {
    return DEFAULT_FOCUS_ITEM_IDS;
  }
}

function persistFocusItemIds(itemIds: string[]) {
  try {
    localStorage.setItem(FOCUS_ITEMS_STORAGE_KEY, JSON.stringify(itemIds));
  } catch {
    // storage unavailable
  }
}

function loadHiddenPluginItemIds(): string[] {
  try {
    const stored = localStorage.getItem(HIDDEN_PLUGIN_ITEMS_STORAGE_KEY);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (itemId): itemId is string =>
        typeof itemId === "string" && !itemId.startsWith("core."),
    );
  } catch {
    return [];
  }
}

function persistHiddenPluginItemIds(itemIds: string[]) {
  try {
    localStorage.setItem(
      HIDDEN_PLUGIN_ITEMS_STORAGE_KEY,
      JSON.stringify(itemIds),
    );
  } catch {
    // storage unavailable
  }
}

export const useSidebarModeStore = create<SidebarModeState>((set) => ({
  mode: (() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored === "simple" ? "simple" : "full";
    } catch {
      return "full";
    }
  })(),

  focusItemIds: loadFocusItemIds(),
  hiddenPluginItemIds: loadHiddenPluginItemIds(),

  toggleMode: () =>
    set((state) => {
      const next: SidebarMode = state.mode === "simple" ? "full" : "simple";
      try {
        if (next === "simple") {
          localStorage.setItem(STORAGE_KEY, "simple");
        } else {
          localStorage.removeItem(STORAGE_KEY);
        }
      } catch {
        // storage unavailable
      }
      return { mode: next };
    }),

  setMode: (mode: SidebarMode) => {
    try {
      if (mode === "simple") {
        localStorage.setItem(STORAGE_KEY, "simple");
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // storage unavailable
    }
    set({ mode });
  },

  setFocusItemIds: (itemIds: string[]) => {
    const next = [...new Set(itemIds)].filter(
      (itemId) => itemId !== "core.inbox",
    );
    persistFocusItemIds(next);
    set({ focusItemIds: next });
  },

  setSidebarItemVisible: (itemId, visible) =>
    set((state) => {
      if (itemId.startsWith("core.")) {
        const next = visible
          ? [...new Set([...state.focusItemIds, itemId])]
          : state.focusItemIds.filter((current) => current !== itemId);
        persistFocusItemIds(next);
        return { focusItemIds: next };
      }

      const hiddenPluginItemIds = visible
        ? state.hiddenPluginItemIds.filter((current) => current !== itemId)
        : [...new Set([...state.hiddenPluginItemIds, itemId])];
      persistHiddenPluginItemIds(hiddenPluginItemIds);
      return { hiddenPluginItemIds };
    }),

  resetFocusItemIds: () => {
    persistFocusItemIds(DEFAULT_FOCUS_ITEM_IDS);
    persistHiddenPluginItemIds([]);
    set({
      focusItemIds: DEFAULT_FOCUS_ITEM_IDS,
      hiddenPluginItemIds: [],
    });
  },
}));
