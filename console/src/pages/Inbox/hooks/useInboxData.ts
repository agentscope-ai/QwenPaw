import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../../../api";
import type { InboxEvent } from "../../../api/modules/console";
import type {
  ApprovalItem,
  HarvestInstance,
  InboxSummary,
  PushMessage,
} from "../types";

const PUSH_POLLING_INTERVAL_MS = 6000;

const MOCK_APPROVALS: ApprovalItem[] = [
  {
    id: "approval-1",
    type: "tool_call",
    title: "Execute Shell Command",
    description: "Agent wants to run `npm install @testing-library/react`",
    requestedBy: "Agent-001",
    requestedAt: new Date(Date.now() - 5 * 60 * 1000),
    priority: "normal",
    status: "pending",
  },
  {
    id: "approval-2",
    type: "file_access",
    title: "File Access Request",
    description: "Agent wants to read `/etc/config/database.yml`",
    requestedBy: "Agent-002",
    requestedAt: new Date(Date.now() - 15 * 60 * 1000),
    priority: "high",
    status: "pending",
  },
  {
    id: "approval-3",
    type: "config_change",
    title: "Configuration Change",
    description: "Agent wants to update shell permission policy",
    requestedBy: "Agent-001",
    requestedAt: new Date(Date.now() - 30 * 60 * 1000),
    priority: "urgent",
    status: "pending",
  },
];

const MOCK_HARVESTS: HarvestInstance[] = [
  {
    id: "harvest-1",
    name: "Tech Frontier Harvest",
    templateId: "tech-daily",
    emoji: "🚀",
    schedule: {
      cron: "0 9 * * *",
      timezone: "Asia/Shanghai",
      nextRun: new Date(Date.now() + 6 * 60 * 60 * 1000),
    },
    status: "active",
    lastGenerated: {
      timestamp: new Date(Date.now() - 2 * 60 * 60 * 1000),
      success: true,
    },
    stats: {
      totalGenerated: 23,
      successRate: 95.6,
      consecutiveDays: 7,
    },
  },
  {
    id: "harvest-2",
    name: "Industry Intelligence",
    templateId: "industry-weekly",
    emoji: "📊",
    schedule: {
      cron: "0 10 * * 1",
      timezone: "Asia/Shanghai",
      nextRun: new Date(Date.now() + 2 * 24 * 60 * 60 * 1000),
    },
    status: "active",
    lastGenerated: {
      timestamp: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000),
      success: true,
    },
    stats: {
      totalGenerated: 12,
      successRate: 100,
      consecutiveDays: 12,
    },
  },
  {
    id: "harvest-3",
    name: "Competitor Watch",
    templateId: "competitor-daily",
    emoji: "🏢",
    schedule: {
      cron: "0 18 * * *",
      timezone: "Asia/Shanghai",
      nextRun: new Date(Date.now() + 8 * 60 * 60 * 1000),
    },
    status: "paused",
    stats: {
      totalGenerated: 5,
      successRate: 80,
      consecutiveDays: 0,
    },
  },
];

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
    approvals: { total: MOCK_APPROVALS.length, urgent: 1 },
    pushMessages: { total: 0, unread: 0 },
    harvests: {
      total: MOCK_HARVESTS.length,
      active: MOCK_HARVESTS.filter((h) => h.status === "active").length,
    },
  });
  const [approvals, setApprovals] = useState<ApprovalItem[]>(MOCK_APPROVALS);
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

  const approveRequest = useCallback((approvalId: string) => {
    setApprovals((prev) =>
      prev.map((item) =>
        item.id === approvalId ? { ...item, status: "approved" } : item,
      ),
    );
  }, []);

  const rejectRequest = useCallback((approvalId: string) => {
    setApprovals((prev) =>
      prev.map((item) =>
        item.id === approvalId ? { ...item, status: "rejected" } : item,
      ),
    );
  }, []);

  const triggerHarvest = useCallback((harvestId: string) => {
    console.info("triggerHarvest", harvestId);
  }, []);

  const pendingApprovals = useMemo(
    () => approvals.filter((item) => item.status === "pending"),
    [approvals],
  );

  useEffect(() => {
    setSummary((prev) => ({
      ...prev,
      approvals: {
        total: pendingApprovals.length,
        urgent: pendingApprovals.filter((item) => item.priority === "urgent")
          .length,
      },
    }));
  }, [pendingApprovals]);

  return {
    summary,
    approvals: pendingApprovals,
    pushMessages,
    harvests,
    markMessageAsRead,
    deleteMessage,
    approveRequest,
    rejectRequest,
    triggerHarvest,
    refreshPushMessages: loadPushMessages,
  };
};
