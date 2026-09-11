/**
 * useOsNotifyPoller.ts — Background poller feeding the notification store.
 *
 * Reuses the same endpoints the sidebar badge relies on, at a 12s cadence,
 * and pauses while the tab is hidden. It never mutates server state; it only
 * maps approvals + unread inbox events into OsNotifyItem and calls ingest().
 */
import { useEffect } from "react";
import api from "../api";
import {
  INBOX_EVENT_QUERY_LIMIT,
  PUSH_MESSAGE_SOURCES,
  isPushMessageEvent,
} from "../utils/inboxEvents";
import { useOsNotify, type OsNotifyItem } from "./osNotifyStore";

const POLL_INTERVAL_MS = 12000;

export function useOsNotifyPoller() {
  const ingest = useOsNotify((s) => s.ingest);

  useEffect(() => {
    let alive = true;

    const load = async () => {
      try {
        const [push, inbox] = await Promise.all([
          api.getPushMessages(),
          api.getInboxEvents({
            unread_only: true,
            limit: INBOX_EVENT_QUERY_LIMIT,
            source_types: [...PUSH_MESSAGE_SOURCES],
          }),
        ]);
        if (!alive) return;

        const approvals: OsNotifyItem[] = (push?.pending_approvals || []).map(
          (a) => ({
            id: `ap:${a.request_id}`,
            kind: "approval",
            title: a.tool_display_name || a.tool_name || "Approval required",
            body: a.findings_summary || `${a.tool_name} · ${a.agent_id}`,
            createdAt: (a.created_at || Date.now() / 1000) * 1000,
            read: false,
            requestId: a.request_id,
            rootSessionId: a.root_session_id,
          }),
        );

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

        ingest(approvals, events, inbox?.unread_count);
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
