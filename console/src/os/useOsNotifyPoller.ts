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
  INBOX_CHANGED_EVENT,
  type InboxChange,
} from "../utils/inboxEvents";
import { useOsNotify, type OsNotifyItem } from "./osNotifyStore";

const POLL_INTERVAL_MS = 12000;

export function useOsNotifyPoller() {
  const ingest = useOsNotify((s) => s.ingest);
  const applyInboxChange = useOsNotify((s) => s.applyInboxChange);

  useEffect(() => {
    let alive = true;
    let loadEpoch = 0;
    let loading = false;

    const load = async (force = false) => {
      if (loading && !force) return;
      loading = true;
      const epoch = ++loadEpoch;
      try {
        const [push, inbox] = await Promise.all([
          api.getPushMessages(),
          api.getInboxEvents({
            unread_only: true,
            limit: INBOX_EVENT_QUERY_LIMIT,
            source_types: [...PUSH_MESSAGE_SOURCES],
            exclude_acl_pending: true,
          }),
        ]);
        if (!alive || epoch !== loadEpoch) return;

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
            sourceType: e.source_type,
            agentId: e.agent_id || undefined,
          }));

        ingest(approvals, events, inbox?.unread_count, inbox?.community_scope);
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
