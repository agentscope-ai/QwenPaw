import { create } from "zustand";

export interface VerifiedEmbedding {
  fingerprint: string;
  dimensions: number;
  latency: number;
  verifiedAt: number;
}

interface EmbeddingVerificationStore {
  verificationByAgent: Record<string, VerifiedEmbedding>;
  setVerification: (agentId: string, verification: VerifiedEmbedding) => void;
  clearVerification: (agentId: string) => void;
}

/**
 * Keep successful embedding checks for the lifetime of the Console session.
 *
 * This state deliberately is not persisted to browser storage: a successful
 * connectivity check is a point-in-time observation and should not survive an
 * application restart. The service fingerprint makes the result valid only
 * for the exact settings that were tested.
 */
export const useEmbeddingVerificationStore = create<EmbeddingVerificationStore>(
  (set) => ({
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
  }),
);
