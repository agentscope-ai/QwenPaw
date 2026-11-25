import { create } from "zustand";

import type { RerankerHistoryRecord } from "@/api/modules/agent";

export interface VerifiedReranker {
  /** In-memory identity of the configuration that was tested. */
  configKey: string;
  latency: number;
  precision: number | null;
  correctCount: number;
  total: number;
  verifiedAt: number;
}

export interface ScopedRerankerHistory {
  configKey: string;
  fingerprint: string;
  records: RerankerHistoryRecord[];
}

interface RerankerVerificationStore {
  verificationByAgent: Record<string, VerifiedReranker>;
  historyByAgent: Record<string, Record<string, ScopedRerankerHistory>>;
  setVerification: (agentId: string, verification: VerifiedReranker) => void;
  setHistory: (
    agentId: string,
    configKey: string,
    records: RerankerHistoryRecord[],
    fingerprint?: string,
  ) => void;
  clearVerification: (agentId: string) => void;
}

/**
 * Keep successful reranker checks for the lifetime of the Console session.
 *
 * This state deliberately is not persisted to browser storage: a successful
 * connectivity check is a point-in-time observation and should not survive an
 * application restart. The configuration key makes the result valid only for
 * the exact settings that were tested.
 *
 * Historical precision series live in a separate slice scoped by both agent
 * and service configuration key (with backend fingerprint metadata). Loading
 * history can never manufacture a "Verified" verdict, switching models within
 * the same agent never shows another model's history, and clearing a failed
 * verification verdict preserves the existing historical trend.
 */
export const useRerankerVerificationStore = create<RerankerVerificationStore>(
  (set) => ({
    verificationByAgent: {},
    historyByAgent: {},
    setVerification: (agentId, verification) =>
      set((state) => ({
        verificationByAgent: {
          ...state.verificationByAgent,
          [agentId]: verification,
        },
      })),
    setHistory: (agentId, configKey, records, fingerprint = "") =>
      set((state) => {
        if (!configKey) return state;
        const agentHistory = state.historyByAgent[agentId] ?? {};
        const existing = agentHistory[configKey];
        const sameService =
          !existing?.fingerprint ||
          !fingerprint ||
          existing.fingerprint === fingerprint;
        if (existing && sameService) {
          const existingLast =
            existing.records[existing.records.length - 1]?.ts ??
            Number.NEGATIVE_INFINITY;
          const incomingLast =
            records[records.length - 1]?.ts ?? Number.NEGATIVE_INFINITY;
          if (incomingLast < existingLast) return state;
        }
        return {
          historyByAgent: {
            ...state.historyByAgent,
            [agentId]: {
              ...agentHistory,
              [configKey]: {
                configKey,
                fingerprint: fingerprint || existing?.fingerprint || "",
                records,
              },
            },
          },
        };
      }),
    clearVerification: (agentId) =>
      set((state) => {
        if (!(agentId in state.verificationByAgent)) {
          return state;
        }
        const verificationByAgent = { ...state.verificationByAgent };
        delete verificationByAgent[agentId];
        return { verificationByAgent };
      }),
  }),
);
