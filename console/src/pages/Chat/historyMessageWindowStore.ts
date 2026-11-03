import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";

export const HISTORY_MESSAGE_WINDOW_CARD = "QwenPawHistoryMessageWindow";

export interface HistoryUserMessage {
  clientMessageId?: string | null;
  messageId: string;
  preview: string;
  createdAt: string;
  anchor: string;
}

export type HistoryNavigationMode = "replace" | "append-newer";

export function splitHistoryMessagesIntoTurnRows(
  messages: IAgentScopeRuntimeWebUIMessage[],
): IAgentScopeRuntimeWebUIMessage[][] {
  if (messages.length === 0) return [];
  const rowsFromNewest: IAgentScopeRuntimeWebUIMessage[][] = [];
  let turnEnd = messages.length;
  for (let index = messages.length - 1; index >= 0; index--) {
    if (messages[index].role !== "user") continue;
    rowsFromNewest.push(messages.slice(index, turnEnd));
    turnEnd = index;
  }
  for (let index = turnEnd - 1; index >= 0; index--) {
    rowsFromNewest.push([messages[index]]);
  }
  return rowsFromNewest.reverse();
}

/** Bound cached history while keeping complete turns and scroll anchors.
 * Oversized turns and the incoming page plus its scroll anchor stay intact. */
export function boundHistoryRows(
  rows: IAgentScopeRuntimeWebUIMessage[][],
  keep: "oldest" | "newest",
  minimumRows = 1,
): IAgentScopeRuntimeWebUIMessage[][] {
  const selected: IAgentScopeRuntimeWebUIMessage[][] = [];
  let bytes = 0;
  const candidates = keep === "oldest" ? rows : [...rows].reverse();
  for (const row of candidates) {
    const size = JSON.stringify(row).length * 2;
    if (
      selected.length >= minimumRows &&
      (selected.length >= 20 || bytes + size > 8 * 1024 * 1024)
    )
      break;
    selected.push(row);
    bytes += size;
  }
  return keep === "oldest" ? selected : selected.reverse();
}

export interface HistoryWindowSnapshot {
  sessionId: string;
  turnRows: IAgentScopeRuntimeWebUIMessage[][];
  loading: boolean;
  canLoadOlder: boolean;
  canLoadNewer?: boolean;
  newerLoadFailed?: boolean;
  userMessages: HistoryUserMessage[];
  onLoadOlder: (target: HTMLElement) => void;
  onFillOlder: (target: HTMLElement) => void;
  onNavigateToUserMessage: (
    message: HistoryUserMessage,
    mode: HistoryNavigationMode,
  ) => void;
  onCancelPending: () => void;
  onReturnToLatest?: () => void;
}

let snapshot: HistoryWindowSnapshot | null = null;
const listeners = new Set<() => void>();

function publish(next: HistoryWindowSnapshot | null) {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

export const historyMessageWindow = {
  begin(
    next: Omit<
      HistoryWindowSnapshot,
      "loading" | "userMessages" | "onNavigateToUserMessage" | "onCancelPending"
    > &
      Partial<
        Pick<
          HistoryWindowSnapshot,
          "userMessages" | "onNavigateToUserMessage" | "onCancelPending"
        >
      >,
  ) {
    publish({
      ...next,
      loading: true,
      userMessages: next.userMessages ?? [],
      onNavigateToUserMessage:
        next.onNavigateToUserMessage ?? (() => undefined),
      onCancelPending: next.onCancelPending ?? (() => undefined),
    });
  },
  setTurnRows(
    sessionId: string,
    turnRows: IAgentScopeRuntimeWebUIMessage[][],
    canLoadOlder: boolean,
  ) {
    if (snapshot?.sessionId === sessionId) {
      publish({ ...snapshot, turnRows, canLoadOlder });
    }
  },
  setLoading(sessionId: string, loading: boolean) {
    if (snapshot?.sessionId === sessionId && snapshot.loading !== loading) {
      publish({ ...snapshot, loading });
    }
  },
  setReturnToLatest(sessionId: string, onReturnToLatest: () => void) {
    if (snapshot?.sessionId === sessionId)
      publish({ ...snapshot, onReturnToLatest });
  },
  setCanLoadNewer(sessionId: string, canLoadNewer: boolean) {
    if (snapshot?.sessionId === sessionId)
      publish({ ...snapshot, canLoadNewer });
  },
  setNewerLoadFailed(sessionId: string, newerLoadFailed: boolean) {
    if (snapshot?.sessionId === sessionId)
      publish({ ...snapshot, newerLoadFailed });
  },
  setUserMessages(sessionId: string, userMessages: HistoryUserMessage[]) {
    if (snapshot?.sessionId === sessionId) {
      publish({ ...snapshot, userMessages });
    }
  },
  end(sessionId?: string) {
    if (!sessionId || snapshot?.sessionId === sessionId) publish(null);
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  getSnapshot() {
    return snapshot;
  },
};

export function createHistoryMessageWindowCard(
  sessionId: string,
): IAgentScopeRuntimeWebUIMessage {
  return {
    id: `qwenpaw-history-window-${sessionId}`,
    role: "assistant",
    history: true,
    cards: [
      {
        code: HISTORY_MESSAGE_WINDOW_CARD,
        data: { sessionId },
      },
    ],
  } as IAgentScopeRuntimeWebUIMessage;
}
