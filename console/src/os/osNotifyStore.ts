/**
 * osNotifyStore.ts — Notification state for the Desktop OS PoC.
 *
 * Aggregates two live sources into macOS-style notifications:
 *   - pending approvals  (api.getPushMessages().pending_approvals)
 *   - unread inbox events (api.getInboxEvents({ unread_only: true }))
 *
 * `ingest` diffs each poll against known ids so only genuinely new items
 * raise a banner (toast). The first poll only seeds known ids to avoid a
 * burst of banners on mount. Badge counts always reflect the current
 * pending/unread totals.
 */
import { create } from "zustand";
import type { InboxChange } from "../utils/inboxEvents";

export type NotifyKind = "approval" | "inbox";

export interface OsNotifyItem {
  /** Stable, namespaced id (e.g. "ap:<request_id>" / "ib:<event_id>"). */
  id: string;
  kind: NotifyKind;
  title: string;
  body: string;
  /** Epoch milliseconds. */
  createdAt: number;
  read: boolean;
  sourceType?: string;
  agentId?: string;
  /** Approval action targets (approval kind only) so the notification can
   *  approve/deny directly via commandsApi.sendApprovalCommand. */
  requestId?: string;
  rootSessionId?: string;
}

const HISTORY_CAP = 50;
const TOAST_CAP = 4;
const KNOWN_INBOX_CAP = 500;

function boundedKnownIds(
  known: ReadonlySet<string>,
  incoming: readonly OsNotifyItem[],
): Set<string> {
  const activeApprovals = incoming
    .filter((item) => item.kind === "approval")
    .map((item) => item.id);
  const inboxIds = [
    ...incoming.filter((item) => item.kind === "inbox").map((item) => item.id),
    ...[...known].filter((id) => id.startsWith("ib:")),
  ].slice(0, KNOWN_INBOX_CAP);
  return new Set([...activeApprovals, ...inboxIds]);
}

interface OsNotifyState {
  history: OsNotifyItem[];
  toasts: OsNotifyItem[];
  approvalCount: number;
  inboxCount: number;
  centerOpen: boolean;
  seeded: boolean;
  knownIds: Set<string>;
  communityScope?: string | null;

  ingest: (
    approvals: OsNotifyItem[],
    inbox: OsNotifyItem[],
    inboxCount?: number,
    communityScope?: string | null,
  ) => void;
  dismissToast: (id: string) => void;
  dismissItem: (id: string) => void;
  setCenter: (open: boolean) => void;
  markAllRead: () => void;
  clearHistory: () => void;
  applyInboxChange: (change: InboxChange) => void;
}

export const useOsNotify = create<OsNotifyState>((set, get) => ({
  history: [],
  toasts: [],
  approvalCount: 0,
  inboxCount: 0,
  centerOpen: false,
  seeded: false,
  knownIds: new Set<string>(),
  communityScope: undefined,

  ingest: (approvals, inbox, exactInboxCount, communityScope) => {
    const state = get();
    const scopeKnown = communityScope !== undefined;
    const scopeChanged =
      scopeKnown &&
      state.communityScope !== undefined &&
      communityScope !== state.communityScope;
    const seedCommunity = scopeKnown && communityScope !== state.communityScope;
    const nextScope = scopeKnown ? communityScope : state.communityScope;
    const oldCommunityIds = new Set(
      [...state.history, ...state.toasts]
        .filter((item) => item.sourceType === "community")
        .map((item) => item.id),
    );
    const keptHistory = scopeChanged
      ? state.history.filter((item) => item.sourceType !== "community")
      : state.history;
    const keptToasts = scopeChanged
      ? state.toasts.filter((item) => item.sourceType !== "community")
      : state.toasts;
    const incoming = [...approvals, ...inbox];
    const approvalCount = approvals.length;
    const inboxCount = exactInboxCount ?? inbox.length;
    const approvalIds = new Set(approvals.map((i) => i.id));

    // Drop approval items no longer pending (resolved from the Inbox, a
    // notification action, or a timeout). Inbox items keep their own
    // read/unread lifecycle and are left untouched.
    const prune = (list: OsNotifyItem[]) =>
      list.filter((i) => i.kind !== "approval" || approvalIds.has(i.id));

    // First poll: seed known ids without raising banners.
    if (!state.seeded) {
      set({
        seeded: true,
        knownIds: boundedKnownIds(new Set(), incoming),
        approvalCount,
        inboxCount,
        communityScope: nextScope,
        history: keptHistory,
        toasts: keptToasts,
      });
      return;
    }

    const known = new Set(
      [...state.knownIds].filter(
        (id) =>
          !scopeChanged ||
          (!id.startsWith("ib:community:") && !oldCommunityIds.has(id)),
      ),
    );
    // The first snapshot for a new community account is a baseline, not a
    // burst of newly arrived mail. Local notifications keep their lifecycle.
    if (seedCommunity) {
      for (const item of inbox)
        if (item.sourceType === "community") known.add(item.id);
    }
    const fresh = incoming.filter((i) => !known.has(i.id));
    fresh.sort((a, b) => b.createdAt - a.createdAt);

    const nextKnown = new Set(known);
    for (const item of fresh) nextKnown.add(item.id);
    // Forget resolved approvals so a later re-request can toast again.
    for (const id of known) {
      if (id.startsWith("ap:") && !approvalIds.has(id)) nextKnown.delete(id);
    }
    const boundedKnown = boundedKnownIds(nextKnown, incoming);

    set({
      approvalCount,
      inboxCount,
      knownIds: boundedKnown,
      communityScope: nextScope,
      history: prune([...fresh, ...keptHistory]).slice(0, HISTORY_CAP),
      toasts: prune([...fresh, ...keptToasts]).slice(0, TOAST_CAP),
    });
  },

  dismissToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  dismissItem: (id) =>
    set((s) => ({
      toasts: s.toasts.filter((t) => t.id !== id),
      history: s.history.filter((h) => h.id !== id),
    })),

  setCenter: (open) =>
    set((s) => ({
      centerOpen: open,
      // Opening the center marks all history entries as seen.
      history: open ? s.history.map((h) => ({ ...h, read: true })) : s.history,
    })),

  markAllRead: () =>
    set((s) => ({ history: s.history.map((h) => ({ ...h, read: true })) })),

  clearHistory: () => set({ history: [], toasts: [] }),

  applyInboxChange: (change) =>
    set((state) => {
      const readIds = new Set((change.readIds || []).map((id) => `ib:${id}`));
      const deletedIds = new Set(
        (change.deletedIds || []).map((id) => `ib:${id}`),
      );
      const removed = (item: OsNotifyItem) =>
        item.kind === "inbox" &&
        (deletedIds.has(item.id) ||
          !!change.clearSources?.includes(item.sourceType || ""));
      const read = (item: OsNotifyItem) =>
        item.kind === "inbox" &&
        (readIds.has(item.id) ||
          (change.readAll &&
            (!change.sourceTypes ||
              change.sourceTypes.includes(item.sourceType || "")) &&
            (!change.agentId || change.agentId === item.agentId)));
      return {
        history: state.history
          .filter((item) => !removed(item))
          .map((item) => (read(item) ? { ...item, read: true } : item)),
        toasts: state.toasts.filter((item) => !removed(item) && !read(item)),
      };
    }),
}));

/** Count of history items not yet seen in the notification center. */
export function unreadNotifyCount(items: OsNotifyItem[]): number {
  return items.filter((i) => !i.read).length;
}
