import { create } from "zustand";

import type { RerankerHistoryRecord } from "@/api/modules/agent";

export interface VerifiedReranker {
  fingerprint: string;
  latency: number;
  precision: number | null;
  correctCount: number;
  total: number;
  history: RerankerHistoryRecord[];
  verifiedAt: number;
}

interface RerankerVerificationStore {
  verificationByAgent: Record<string, VerifiedReranker>;
  setVerification: (agentId: string, verification: VerifiedReranker) => void;
  clearVerification: (agentId: string) => void;
}

/**
 * Keep successful reranker checks for the lifetime of the Console session.
 *
 * This state deliberately is not persisted to browser storage: a successful
 * connectivity check is a point-in-time observation and should not survive an
 * application restart. The service fingerprint makes the result valid only
 * for the exact settings that were tested.
 */
export const useRerankerVerificationStore =
  create<RerankerVerificationStore>((set) => ({
    verificationByAgent: {},
    setVerification: (agentId, verification) =>
      set((state) => ({
        verificationByAgent: {
          ...state.verificationByAgent,
          [agentId]: verification,
        },
      })),
    clearVerification: (agentId) =>
      set((state) => {
        if (!(agentId in state.verificationByAgent)) return state;
        const verificationByAgent = { ...state.verificationByAgent };
        delete verificationByAgent[agentId];
        return { verificationByAgent };
      }),
  }));
