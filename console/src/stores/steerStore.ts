import { create } from "zustand";
import type { SteerReceipt } from "../pages/Chat/steerTimeline";

import type { HistorySteer } from "../api/types/chat";

export const EMPTY_STEERS: SteerReceipt[] = [];
export const useSteerStore = create<{
  receipts: Record<string, SteerReceipt[]>;
  historySync: Record<string, { scope: string; needs_sync: boolean }>;
  hydrateHistory: (visit: string, scope: string, data: HistorySteer) => void;
  merge: (scope: string, receipts: SteerReceipt[]) => void;
  retry: Record<string, (turnId?: string) => Promise<unknown>>;
  bindRetry: (
    scope: string,
    retry?: (turnId?: string) => Promise<unknown>,
  ) => void;
}>((set) => ({
  receipts: {},
  historySync: {},
  hydrateHistory: (visit, scope, data) => {
    // Page snapshots initialize scheduling, never overwrite live knowledge.
    set((state) =>
      state.historySync[visit]
        ? state
        : {
            historySync: {
              ...state.historySync,
              [visit]: {
                scope,
                needs_sync: data.needs_sync,
              },
            },
          },
    );
    useSteerStore
      .getState()
      .merge(scope, Object.values(data.receipts_by_turn).flat());
  },
  retry: {},
  bindRetry: (scope, retry) =>
    set((state) => {
      const next = { ...state.retry };
      if (retry) next[scope] = retry;
      else {
        delete next[scope];
        const receipts = { ...state.receipts };
        delete receipts[scope];
        const historySync = Object.fromEntries(
          Object.entries(state.historySync).filter(
            ([, value]) => value.scope !== scope,
          ),
        );
        return { retry: next, receipts, historySync };
      }
      return { retry: next };
    }),
  merge: (scope, incoming) =>
    set((state) => {
      const values = new Map(
        (state.receipts[scope] || []).map((r) => [r.client_message_id, r]),
      );
      let changed = false;
      for (const receipt of incoming) {
        const previous = values.get(receipt.client_message_id);
        if (previous && receipt.revision < previous.revision) continue;
        if (
          previous &&
          receipt.revision === previous.revision &&
          receipt.status === previous.status &&
          receipt.reason === previous.reason &&
          (!receipt.message || previous.message)
        )
          continue;
        changed = true;
        values.set(receipt.client_message_id, {
          ...receipt,
          message: receipt.message || previous?.message,
        });
      }
      if (!changed) return state;
      return { receipts: { ...state.receipts, [scope]: [...values.values()] } };
    }),
}));
