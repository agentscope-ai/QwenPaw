import { useCallback, useEffect, useState } from "react";
import api from "../../../api";
import type { InboxEvent } from "../../../api/modules/console";
import type { HarvestInstance, InboxSummary, PushMessage } from "../types";

const PUSH_POLLING_INTERVAL_MS = 6000;

const MOCK_HARVESTS: HarvestInstance[] = [];

const mapPriority = (text: string): "low" | "normal" | "high" | "urgent" => {
  if (text.includes("❌") || text.toLowerCase().includes("error")) {
    return "high";
  }
  return "normal";
};

const stripExecutionTimeText = (text: string): string =>
  text.replace(/\s*duration=\d+ms\.?/gi, "").trim();

const mapEventToPushMessage = (event: InboxEvent): PushMessage => ({
  id: event.id,
  channelType:
    event.source_type === "heartbeat"
      ? "discord"
      : event.source_type === "cron"
      ? "wechat"
      : "email",
  channelName:
    event.source_type === "heartbeat"
      ? "Heartbeat"
      : event.source_type === "cron"
      ? "Cron"
      : "System",
  title: event.title,
  content: stripExecutionTimeText(event.body),
  sender: {
    userId: event.agent_id || "default",
    username: event.agent_id || "default",
  },
  createdAt: new Date((event.created_at || Date.now() / 1000) * 1000),
  read: Boolean(event.read),
  metadata: {
    priority:
      event.severity === "error" || event.status === "error"
        ? "high"
        : mapPriority(event.body),
    sourceType: event.source_type,
    sourceId: event.source_id,
    eventType: event.event_type,
    status: event.status,
    severity: event.severity,
    trigger:
      typeof event.payload?.trigger === "string"
        ? (event.payload.trigger as string)
        : undefined,
    agentId: event.agent_id,
    payload:
      event.payload && typeof event.payload === "object"
        ? event.payload
        : undefined,
  },
});

export const useInboxData = () => {
  const [summary, setSummary] = useState<InboxSummary>({
    approvals: { total: 0, urgent: 0 },
    pushMessages: { total: 0, unread: 0 },
    harvests: {
      total: MOCK_HARVESTS.length,
      active: MOCK_HARVESTS.filter((h) => h.status === "active").length,
    },
  });
  const [pushMessages, setPushMessages] = useState<PushMessage[]>([]);
  const [harvests] = useState<HarvestInstance[]>(MOCK_HARVESTS);

  const loadPushMessages = useCallback(async () => {
    try {
      const res = await api.getInboxEvents({ limit: 200, source_type: "cron" });
      const events = [...(res?.events || [])];
      events.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      const nextItems: PushMessage[] = events.map(mapEventToPushMessage);
      setPushMessages(nextItems);
      setSummary((prev) => ({
        ...prev,
        pushMessages: {
          total: nextItems.length,
          unread: nextItems.filter((m) => !m.read).length,
        },
      }));
    } catch (error) {
      console.error("Failed to fetch push inbox data", error);
    }
  }, []);

  useEffect(() => {
    void loadPushMessages();
    const timer = window.setInterval(() => {
      void loadPushMessages();
    }, PUSH_POLLING_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadPushMessages]);

  const markMessageAsRead = useCallback((messageId: string) => {
    void api.markInboxRead({ event_ids: [messageId] });
    setPushMessages((prev) =>
      prev.map((message) =>
        message.id === messageId ? { ...message, read: true } : message,
      ),
    );
    setSummary((prev) => ({
      ...prev,
      pushMessages: {
        ...prev.pushMessages,
        unread: Math.max(prev.pushMessages.unread - 1, 0),
      },
    }));
  }, []);

  const markAllMessagesAsRead = useCallback(async (): Promise<number> => {
    const unreadIds = pushMessages
      .filter((message) => !message.read)
      .map((m) => m.id);
    if (!unreadIds.length) {
      return 0;
    }
    await api.markInboxRead({ all: true });
    setPushMessages((prev) =>
      prev.map((message) =>
        message.read ? message : { ...message, read: true },
      ),
    );
    setSummary((prev) => ({
      ...prev,
      pushMessages: {
        ...prev.pushMessages,
        unread: 0,
      },
    }));
    return unreadIds.length;
  }, [pushMessages]);

  const deleteMessage = useCallback((messageId: string) => {
    void api.deleteInboxEvent(messageId);
    let unreadDelta = 0;
    setPushMessages((prev) => {
      const removed = prev.find((message) => message.id === messageId);
      unreadDelta = removed && !removed.read ? 1 : 0;
      return prev.filter((message) => message.id !== messageId);
    });
    setSummary((prev) => ({
      ...prev,
      pushMessages: {
        total: Math.max(prev.pushMessages.total - 1, 0),
        unread: Math.max(prev.pushMessages.unread - unreadDelta, 0),
      },
    }));
  }, []);

  const triggerHarvest = useCallback((harvestId: string) => {
    console.info("triggerHarvest", harvestId);
  }, []);

  return {
    summary,
    pushMessages,
    harvests,
    markMessageAsRead,
    markAllMessagesAsRead,
    deleteMessage,
    triggerHarvest,
    refreshPushMessages: loadPushMessages,
  };
};
