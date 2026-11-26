import { create } from "zustand";

/**
 * Cross-component hand-off for "look at these reviews". The decision tray owns
 * its own focus/flash state, so a blocked production confirmation (inside the
 * tray) cannot reach it directly. A focus request contains the review ids the
 * backend reported as blocking plus a nonce, so repeated clicks re-focus and
 * re-flash instead of being swallowed by equality checks.
 */
interface DecisionFocusState {
  reviewIds: string[];
  nonce: number;
  /** Record blockers without stealing focus (used when a 409 arrives). */
  noteBlockingReviews: (reviewIds: string[]) => void;
  /** Pull the tray to these reviews and flash; omitted ids reuse the last 409. */
  focusReviews: (reviewIds?: string[]) => void;
  clear: () => void;
}

export const useDecisionFocusStore = create<DecisionFocusState>((set) => ({
  reviewIds: [],
  nonce: 0,
  noteBlockingReviews: (reviewIds) => set({ reviewIds: dedupe(reviewIds) }),
  focusReviews: (reviewIds) =>
    set((state) => ({
      reviewIds: reviewIds ? dedupe(reviewIds) : state.reviewIds,
      nonce: state.nonce + 1,
    })),
  clear: () => set({ reviewIds: [], nonce: 0 }),
}));

function dedupe(reviewIds: string[]): string[] {
  return reviewIds.filter(
    (id, index) => typeof id === "string" && reviewIds.indexOf(id) === index,
  );
}
