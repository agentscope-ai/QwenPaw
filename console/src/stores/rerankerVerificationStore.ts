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

interface RerankerVerificationStore {
  verificationByAgent: Record<string, VerifiedReranker>;
  historyByAgent: Record<string, RerankerHistoryRecord[]>;
  setVerification: (agentId: string, verification: VerifiedReranker) => void;
  setHistory: (agentId: string, records: RerankerHistoryRecord[]) => void;
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
 * Historical precision series live in a separate slice. Loading history can
 * therefore never manufacture a "Verified" verdict, and a late history
 * response cannot overwrite a newer manual result.
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
    setHistory: (agentId, records) =>
      set((state) => ({
        historyByAgent: {
          ...state.historyByAgent,
          [agentId]: records,
        },
      })),
    clearVerification: (agentId) =>
      set((state) => {
        if (
          !(agentId in state.verificationByAgent) &&
          !(agentId in state.historyByAgent)
        ) {
          return state;
        }
        const verificationByAgent = { ...state.verificationByAgent };
        const historyByAgent = { ...state.historyByAgent };
        delete verificationByAgent[agentId];
        delete historyByAgent[agentId];
        return { verificationByAgent, historyByAgent };
      }),
  }),
);