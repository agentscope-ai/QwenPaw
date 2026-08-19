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

  ingest: (
    approvals: OsNotifyItem[],
    inbox: OsNotifyItem[],
    inboxCount?: number,
  ) => void;
  dismissToast: (id: string) => void;
  dismissItem: (id: string) => void;
  setCenter: (open: boolean) => void;
  markAllRead: () => void;
  clearHistory: () => void;
}

export const useOsNotify = create<OsNotifyState>((set, get) => ({
  history: [],
  toasts: [],
  approvalCount: 0,
  inboxCount: 0,
  centerOpen: false,
  seeded: false,
  knownIds: new Set<string>(),

  ingest: (approvals, inbox, exactInboxCount) => {
    const state = get();
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
      });
      return;
    }

    const known = state.knownIds;
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
      history: prune([...fresh, ...state.history]).slice(0, HISTORY_CAP),
      toasts: prune([...fresh, ...state.toasts]).slice(0, TOAST_CAP),
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
}));

/** Count of history items not yet seen in the notification center. */
export function unreadNotifyCount(items: OsNotifyItem[]): number {
  return items.filter((i) => !i.read).length;
}
