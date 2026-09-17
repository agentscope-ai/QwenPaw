import { create } from "zustand";
import type { TurnUsageSnapshot } from "./turnUsage";

interface TurnUsageStore {
  snapshot: TurnUsageSnapshot | null;
  setSnapshot: (snapshot: TurnUsageSnapshot | null) => void;
  activeTurn: TurnUsageToken | null;
  beginTurn: (agentId: string, sessionId: string) => TurnUsageToken;
  setSnapshotForTurn: (
    snapshot: TurnUsageSnapshot | null,
    turn: TurnUsageToken,
  ) => boolean;
  isTurnActive: (turn: TurnUsageToken) => boolean;
  invalidateTurn: () => void;
  /** Current agent active model's effective context window (from ModelSelector). */
  activeMaxInputLength: number | null;
  setActiveMaxInputLength: (maxInputLength: number | null) => void;
}

export interface TurnUsageToken {
  agentId: string;
  sessionId: string;
  revision: number;
}

let nextTurnRevision = 0;

function isSameTurn(
  activeTurn: TurnUsageToken | null,
  turn: TurnUsageToken,
): boolean {
  return (
    activeTurn?.agentId === turn.agentId &&
    activeTurn.sessionId === turn.sessionId &&
    activeTurn.revision === turn.revision
  );
}

export const useTurnUsageStore = create<TurnUsageStore>((set, get) => ({
  snapshot: null,
  setSnapshot: (snapshot) => set({ snapshot }),
  activeTurn: null,
  beginTurn: (agentId, sessionId) => {
    const turn = {
      agentId,
      sessionId,
      revision: ++nextTurnRevision,
    };
    set((state) => ({
      activeTurn: turn,
      // Keep the previous session projection visible while the next response
      // streams. The completed turn replaces it through setSnapshotForTurn.
      snapshot: state.snapshot,
    }));
    return turn;
  },
  setSnapshotForTurn: (snapshot, turn) => {
    if (!isSameTurn(get().activeTurn, turn)) return false;
    set({ snapshot });
    return true;
  },
  isTurnActive: (turn) => isSameTurn(get().activeTurn, turn),
  invalidateTurn: () => set({ activeTurn: null, snapshot: null }),
  activeMaxInputLength: null,
  setActiveMaxInputLength: (activeMaxInputLength) =>
    set({ activeMaxInputLength }),
}));
