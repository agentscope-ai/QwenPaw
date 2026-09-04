import { create } from "zustand";

import { isFixedSidebarItemId } from "@/constants/sidebarItems";

const FOCUS_ITEMS_STORAGE_KEY = "qwenpaw_sidebar_focus_items_v1";
const HIDDEN_PLUGIN_ITEMS_STORAGE_KEY =
  "qwenpaw_sidebar_hidden_plugin_items_v1";

export const DEFAULT_FOCUS_ITEM_IDS = [
  "core.cron-jobs",
  "core.files",
  "core.agent-config",
  "core.models",
];

interface SidebarStoreState {
  focusItemIds: string[];
  hiddenPluginItemIds: string[];
  setFocusItemIds: (itemIds: string[]) => void;
  setSidebarItemVisible: (itemId: string, visible: boolean) => void;
  setSidebarItemsVisible: (itemIds: string[], visible: boolean) => void;
  invertSidebarItems: (itemIds: string[]) => void;
  resetFocusItemIds: () => void;
}

interface SidebarVisibilityState {
  focusItemIds: string[];
  hiddenPluginItemIds: string[];
}

function loadFocusItemIds(): string[] {
  try {
    const stored = localStorage.getItem(FOCUS_ITEMS_STORAGE_KEY);
    if (!stored) return [...DEFAULT_FOCUS_ITEM_IDS];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [...DEFAULT_FOCUS_ITEM_IDS];
    return parsed.filter(
      (itemId): itemId is string =>
        typeof itemId === "string" && !isFixedSidebarItemId(itemId),
    );
  } catch {
    return [...DEFAULT_FOCUS_ITEM_IDS];
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

function updateSidebarItemsVisibility(
  state: SidebarVisibilityState,
  itemIds: string[],
  resolveVisible: (currentlyVisible: boolean) => boolean,
): SidebarVisibilityState {
  const focusItemIds = new Set(state.focusItemIds);
  const hiddenPluginItemIds = new Set(state.hiddenPluginItemIds);
  const configurableItemIds = [...new Set(itemIds)].filter(
    (itemId) => !isFixedSidebarItemId(itemId),
  );

  for (const itemId of configurableItemIds) {
    if (itemId.startsWith("core.")) {
      const visible = resolveVisible(focusItemIds.has(itemId));
      if (visible) focusItemIds.add(itemId);
      else focusItemIds.delete(itemId);
    } else {
      const visible = resolveVisible(!hiddenPluginItemIds.has(itemId));
      if (visible) hiddenPluginItemIds.delete(itemId);
      else hiddenPluginItemIds.add(itemId);
    }
  }

  const next = {
    focusItemIds: [...focusItemIds],
    hiddenPluginItemIds: [...hiddenPluginItemIds],
  };
  persistFocusItemIds(next.focusItemIds);
  persistHiddenPluginItemIds(next.hiddenPluginItemIds);
  return next;
}

export const useSidebarStore = create<SidebarStoreState>((set) => ({
  focusItemIds: loadFocusItemIds(),
  hiddenPluginItemIds: loadHiddenPluginItemIds(),

  setFocusItemIds: (itemIds: string[]) => {
    const next = [...new Set(itemIds)].filter(
      (itemId) => !isFixedSidebarItemId(itemId),
    );
    persistFocusItemIds(next);
    set({ focusItemIds: next });
  },

  setSidebarItemVisible: (itemId, visible) =>
    set((state) => {
      if (isFixedSidebarItemId(itemId)) return state;

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

  setSidebarItemsVisible: (itemIds, visible) =>
    set((state) => updateSidebarItemsVisibility(state, itemIds, () => visible)),

  invertSidebarItems: (itemIds) =>
    set((state) =>
      updateSidebarItemsVisibility(
        state,
        itemIds,
        (currentlyVisible) => !currentlyVisible,
      ),
    ),

  resetFocusItemIds: () => {
    persistFocusItemIds(DEFAULT_FOCUS_ITEM_IDS);
    persistHiddenPluginItemIds([]);
    set({
      focusItemIds: [...DEFAULT_FOCUS_ITEM_IDS],
      hiddenPluginItemIds: [],
    });
  },
}));
