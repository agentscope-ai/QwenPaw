/**
 * useOsNotifyPoller.ts — Background poller feeding the notification store.
 *
 * Polls unread inbox events at a 12s cadence and pauses while the tab is
 * hidden. Pending approvals come from ConsolePollService through the shared
 * ApprovalContext, keeping /console/push-messages under one polling owner.
 */
import { useEffect, useRef } from "react";
import api from "../api";
import type { PendingApproval } from "../api/modules/console";
import { useApprovalContext } from "../contexts/ApprovalContext";
import {
  INBOX_EVENT_QUERY_LIMIT,
  PUSH_MESSAGE_SOURCES,
  isPushMessageEvent,
  INBOX_CHANGED_EVENT,
  type InboxChange,
} from "../utils/inboxEvents";
import { useOsNotify, type OsNotifyItem } from "./osNotifyStore";

const POLL_INTERVAL_MS = 12000;

function mapApprovals(approvals: PendingApproval[]): OsNotifyItem[] {
  return approvals.map((approval) => ({
    id: `ap:${approval.request_id}`,
    kind: "approval",
    title:
      approval.tool_display_name || approval.tool_name || "Approval required",
    body:
      approval.findings_summary ||
      `${approval.tool_name} · ${approval.agent_id}`,
    createdAt: (approval.created_at || Date.now() / 1000) * 1000,
    read: false,
    requestId: approval.request_id,
    rootSessionId: approval.root_session_id,
  }));
}

export function useOsNotifyPoller() {
  const ingest = useOsNotify((s) => s.ingest);
  const applyInboxChange = useOsNotify((s) => s.applyInboxChange);
  const { approvals } = useApprovalContext();
  const approvalsRef = useRef(approvals);
  const inboxRef = useRef<OsNotifyItem[]>([]);
  const inboxCountRef = useRef<number>();
  const communityScopeRef = useRef<string | null>();
  const hasInboxSnapshotRef = useRef(false);

  approvalsRef.current = approvals;

  useEffect(() => {
    if (!hasInboxSnapshotRef.current) return;
    ingest(
      mapApprovals(approvals),
      inboxRef.current,
      inboxCountRef.current,
      communityScopeRef.current,
    );
  }, [approvals, ingest]);

  useEffect(() => {
    let alive = true;
    let loadEpoch = 0;
    let loading = false;

    const load = async (force = false) => {
      if (loading && !force) return;
      loading = true;
      const epoch = ++loadEpoch;
      try {
        const inbox = await api.getInboxEvents({
          unread_only: true,
          limit: INBOX_EVENT_QUERY_LIMIT,
          source_types: [...PUSH_MESSAGE_SOURCES],
          exclude_acl_pending: true,
        });
        if (!alive || epoch !== loadEpoch) return;

        const events: OsNotifyItem[] = (inbox?.events || [])
          .filter(isPushMessageEvent)
          .map((e) => ({
            id: `ib:${e.id}`,
            kind: "inbox",
            title: e.title || "Inbox message",
            body: e.body || "",
            createdAt: (e.created_at || Date.now() / 1000) * 1000,
            read: false,
            sourceType: e.source_type,
            agentId: e.agent_id || undefined,
          }));

        inboxRef.current = events;
        inboxCountRef.current = inbox?.unread_count;
        communityScopeRef.current = inbox?.community_scope;
        hasInboxSnapshotRef.current = true;
        ingest(
          mapApprovals(approvalsRef.current),
          events,
          inbox?.unread_count,
          inbox?.community_scope,
        );
      } catch {
        // Backend offline in PoC — keep previous state silently.
      } finally {
        if (epoch === loadEpoch) loading = false;
      }
    };

    void load();
    let timer: number | null = null;
    const start = () => {
      if (timer == null)
        timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    };
    const stop = () => {
      if (timer != null) {
        window.clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void load();
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    const onInboxChanged = (event: Event) => {
      applyInboxChange((event as CustomEvent<InboxChange>).detail || {});
      // Keep approval-context updates from restoring an obsolete inbox snapshot.
      const state = useOsNotify.getState();
      inboxRef.current = state.history.filter(
        (item) => item.kind === "inbox" && !item.read,
      );
      inboxCountRef.current = state.inboxCount;
      communityScopeRef.current = state.communityScope;
      void load(true);
    };
    window.addEventListener(INBOX_CHANGED_EVENT, onInboxChanged);
    return () => {
      alive = false;
      loadEpoch += 1;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener(INBOX_CHANGED_EVENT, onInboxChanged);
    };
  }, [ingest, applyInboxChange]);
}
