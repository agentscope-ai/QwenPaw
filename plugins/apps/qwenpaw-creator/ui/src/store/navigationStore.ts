import { create } from "zustand";

/**
 * Cross-context navigation location stack (design doc 3.2, iteration plan 1.5).
 *
 * Before a jump, the source location's full state (route, selected object,
 * scroll position) is saved; after the jump a return banner renders at the top;
 * user-initiated navigation clears the stack.
 */
export interface SavedLocation {
  /** Hash route path, e.g. /project/xxx/assets */
  path: string;
  description: string;
  /** Selected object ref (element:xxx / timeline:xxx / asset-version:xxx) */
  selectedRef?: string;
  /** scrollTop of the main scroll container */
  scrollTop?: number;
  savedAt: number;
}

export interface ReviewFocusRequest {
  path: string;
  ref: string;
  query: Record<string, string>;
  nonce: number;
}

interface NavigationStore {
  stack: SavedLocation[];
  /** Selection/scroll to apply after restore; consumed by the target page. */
  pendingRestore: SavedLocation | null;
  /**
   * Latest review-focus request; same-route repeat clicks still bump the
   * nonce so the target page replays the flash.
   */
  reviewFocus: ReviewFocusRequest | null;
  /**
   * Target path (without query) of the last navigateToRef / returnToSavedLocation
   * jump. Distinguishes "controlled jumps" from "user-initiated navigation" —
   * the latter should clear the location stack.
   */
  expectedPath: string | null;
  pushLocation: (location: Omit<SavedLocation, "savedAt">) => void;
  popLocation: () => SavedLocation | null;
  setExpectedPath: (path: string | null) => void;
  setReviewFocus: (request: Omit<ReviewFocusRequest, "nonce">) => void;
  clear: () => void;
  consumeRestore: () => SavedLocation | null;
}

export const useNavigationStore = create<NavigationStore>((set, get) => ({
  stack: [],
  pendingRestore: null,
  reviewFocus: null,
  expectedPath: null,

  pushLocation: (location) => {
    set((state) => ({
      stack: [...state.stack, { ...location, savedAt: Date.now() }].slice(-10),
    }));
  },

  popLocation: () => {
    const { stack } = get();
    if (stack.length === 0) return null;
    const top = stack[stack.length - 1];
    set({ stack: stack.slice(0, -1), pendingRestore: top });
    return top;
  },

  setExpectedPath: (path) => set({ expectedPath: path }),
  setReviewFocus: (request) =>
    set({ reviewFocus: { ...request, nonce: Date.now() } }),

  clear: () =>
    set({
      stack: [],
      pendingRestore: null,
      reviewFocus: null,
      expectedPath: null,
    }),

  consumeRestore: () => {
    const { pendingRestore } = get();
    if (pendingRestore) set({ pendingRestore: null });
    return pendingRestore;
  },
}));
