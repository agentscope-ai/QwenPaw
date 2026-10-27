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
  const { approvals } = useApprovalContext();
  const approvalsRef = useRef(approvals);
  const inboxRef = useRef<OsNotifyItem[]>([]);
  const inboxCountRef = useRef<number>();
  const hasInboxSnapshotRef = useRef(false);

  approvalsRef.current = approvals;

  useEffect(() => {
    if (!hasInboxSnapshotRef.current) return;
    ingest(mapApprovals(approvals), inboxRef.current, inboxCountRef.current);
  }, [approvals, ingest]);

  useEffect(() => {
    let alive = true;

    const load = async () => {
      try {
        const inbox = await api.getInboxEvents({
          unread_only: true,
          limit: INBOX_EVENT_QUERY_LIMIT,
          source_types: [...PUSH_MESSAGE_SOURCES],
        });
        if (!alive) return;

        const events: OsNotifyItem[] = (inbox?.events || [])
          .filter(isPushMessageEvent)
          .map((e) => ({
            id: `ib:${e.id}`,
            kind: "inbox",
            title: e.title || "Inbox message",
            body: e.body || "",
            createdAt: (e.created_at || Date.now() / 1000) * 1000,
            read: false,
          }));

        inboxRef.current = events;
        inboxCountRef.current = inbox?.unread_count;
        hasInboxSnapshotRef.current = true;
        ingest(mapApprovals(approvalsRef.current), events, inbox?.unread_count);
      } catch {
        // Backend offline in PoC — keep previous state silently.
      }
    };

    void load();
    let timer: number | null = null;
    const start = () => {
      if (timer == null) timer = window.setInterval(load, POLL_INTERVAL_MS);
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
    return () => {
      alive = false;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [ingest]);
}
