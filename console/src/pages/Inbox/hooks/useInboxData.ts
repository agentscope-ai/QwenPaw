import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import api from "../../../api";
import type { InboxEvent } from "../../../api/modules/console";
import { useAgentStore } from "../../../stores/agentStore";
import {
  DEFAULT_AGENT_ID,
  getAgentDisplayName,
} from "../../../utils/agentDisplayName";
import {
  INBOX_EVENT_QUERY_LIMIT,
  PUSH_MESSAGE_SOURCES,
  isPushMessageEvent,
} from "../../../utils/inboxEvents";
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

const getHeartbeatSummary = (status?: string): string => {
  const normalizedStatus = (status || "").toLowerCase();
  if (normalizedStatus === "success") {
    return "Heartbeat 执行成功";
  }
  if (normalizedStatus === "timeout") {
    return "Heartbeat 执行超时";
  }
  if (normalizedStatus === "cancelled") {
    return "Heartbeat 已取消";
  }
  return "Heartbeat 执行失败";
};

const getSkillAutoSyncSummary = (event: InboxEvent, t: TFunction): string => {
  const payload = (event.payload || {}) as {
    synced?: { skill?: string; agents?: string[] }[];
    failed?: { skill?: string; agents?: string[] }[];
  };
  const parts: string[] = [];
  for (const item of payload.synced || []) {
    parts.push(
      t("inbox.skillAutoSynced", {
        skill: item.skill,
        agents: (item.agents || []).join(", "),
      }),
    );
  }
  for (const item of payload.failed || []) {
    parts.push(
      t("inbox.skillAutoSyncFailed", {
        skill: item.skill,
        agents: (item.agents || []).join(", "),
      }),
    );
  }
  return parts.join("; ") || event.body;
};

const getBuiltinAutoUpdateSummary = (
  event: InboxEvent,
  t: TFunction,
): string => {
  const payload = (event.payload || {}) as {
    pool_updated?: {
      skill?: string;
      from_version?: string;
      to_version?: string;
    }[];
    pool_failed?: { skill?: string }[];
    synced?: { skill?: string; agents?: string[] }[];
    sync_failed?: { skill?: string; agents?: string[] }[];
  };
  const parts: string[] = [];
  for (const item of payload.pool_updated || []) {
    parts.push(
      t("inbox.skillBuiltinUpdated", {
        skill: item.skill,
        from: item.from_version || "-",
        to: item.to_version || "-",
      }),
    );
  }
  for (const item of payload.pool_failed || []) {
    parts.push(t("inbox.skillBuiltinUpdateFailed", { skill: item.skill }));
  }
  for (const item of payload.synced || []) {
    parts.push(
      t("inbox.skillBuiltinSynced", {
        skill: item.skill,
        agents: (item.agents || []).join(", "),
      }),
    );
  }
  for (const item of payload.sync_failed || []) {
    parts.push(
      t("inbox.skillBuiltinSyncFailed", {
        skill: item.skill,
        agents: (item.agents || []).join(", "),
      }),
    );
  }
  return parts.join("; ") || event.body;
};

const isBuiltinAutoUpdateEvent = (event: InboxEvent): boolean => {
  if (event.event_type !== "auto_update") return false;
  const payload = (event.payload || {}) as Record<string, unknown>;
  // Before the naming split, Auto Sync events were also stored as
  // `auto_update`. Their payload only had `synced` / `failed`, so keep those
  // historical messages displayed as Auto Sync.
  return (
    "pool_updated" in payload ||
    "pool_failed" in payload ||
    "sync_failed" in payload
  );
};

const getChannelType = (sourceType: string): PushMessage["channelType"] => {
  switch (sourceType) {
    case "heartbeat":
      return "heartbeat";
    case "memory":
      return "memory";
    case "cron":
      return "wechat";
    case "skill_autoupdate":
      return "skill";
    default:
      return "email";
  }
};

const getChannelName = (event: InboxEvent, t: TFunction): string => {
  switch (event.source_type) {
    case "heartbeat":
      return "Heartbeat";
    case "memory":
      return "Memory";
    case "cron":
      return "Cron";
    case "skill_autoupdate":
      return isBuiltinAutoUpdateEvent(event)
        ? t("skillPool.builtinAutoUpdate")
        : t("skillPool.autoSync");
    case "mail":
      return "Mail";
    default:
      return "System";
  }
};

const mapEventToPushMessage = (
  event: InboxEvent,
  resolveAgentName: (agentId: string) => string,
  t: TFunction,
): PushMessage => {
  const isSkillAutomation = event.source_type === "skill_autoupdate";
  const isBuiltinUpdate = isSkillAutomation && isBuiltinAutoUpdateEvent(event);
  let title = event.title;
  let content = stripExecutionTimeText(event.body);
  if (event.source_type === "heartbeat") {
    content = getHeartbeatSummary(event.status);
  } else if (isBuiltinUpdate) {
    title = t("inbox.skillBuiltinAutoUpdateTitle");
    content = getBuiltinAutoUpdateSummary(event, t);
  } else if (isSkillAutomation) {
    title = t("inbox.skillAutoSyncTitle");
    content = getSkillAutoSyncSummary(event, t);
  }

  return {
    id: event.id,
    channelType: getChannelType(event.source_type),
    channelName: getChannelName(event, t),
    title,
    content,
    sender: {
      userId: event.agent_id || "default",
      username: isSkillAutomation
        ? t("inbox.skillPoolSender")
        : resolveAgentName(event.agent_id || DEFAULT_AGENT_ID),
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
  };
};

export const useInboxData = () => {
  const { t } = useTranslation();
  const agents = useAgentStore((state) => state.agents);
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );
  const resolveAgentName = useCallback(
    (agentId: string) => {
      const normalizedId = agentId || DEFAULT_AGENT_ID;
      const agent = agentsById.get(normalizedId);
      if (agent) {
        return getAgentDisplayName(agent, t);
      }
      if (normalizedId === DEFAULT_AGENT_ID) {
        return t("agent.defaultDisplayName");
      }
      return normalizedId;
    },
    [agentsById, t],
  );
  const resolveAgentNameRef = useRef(resolveAgentName);
  resolveAgentNameRef.current = resolveAgentName;
  const tRef = useRef(t);
  tRef.current = t;
  const [summary, setSummary] = useState<InboxSummary>({
    approvals: { total: 0, urgent: 0 },
    pushMessages: { total: 0, unread: 0 },
    harvests: {
      total: MOCK_HARVESTS.length,
      active: MOCK_HARVESTS.filter((h) => h.status === "active").length,
    },
  });
  const [pushMessages, setPushMessages] = useState<PushMessage[]>([]);
  const pushMessagesRef = useRef(pushMessages);
  pushMessagesRef.current = pushMessages;
  const [harvests] = useState<HarvestInstance[]>(MOCK_HARVESTS);

  const loadPushMessages = useCallback(async () => {
    try {
      const res = await api.getInboxEvents({
        limit: INBOX_EVENT_QUERY_LIMIT,
        source_types: [...PUSH_MESSAGE_SOURCES],
      });
      const events = [...(res?.events || [])].filter(
        (event) =>
          isPushMessageEvent(event) &&
          // Pending-approval mail events are handled in the mail access
          // control drawer; keep them out of the push message list.
          (event.payload as Record<string, unknown> | undefined)?.acl_status !==
            "pending",
      );
      events.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      const nextItems: PushMessage[] = events.map((event) =>
        mapEventToPushMessage(event, resolveAgentNameRef.current, tRef.current),
      );
      setPushMessages(nextItems);
      setSummary((prev) => ({
        ...prev,
        pushMessages: {
          total: res?.total ?? nextItems.length,
          unread: res?.unread_count ?? nextItems.filter((m) => !m.read).length,
        },
      }));
    } catch (error) {
      console.error("Failed to fetch push inbox data", error);
    }
  }, []);

  useEffect(() => {
    void loadPushMessages();

    let timer: number | null = null;

    const startPolling = () => {
      if (timer) return;
      timer = window.setInterval(() => {
        void loadPushMessages();
      }, PUSH_POLLING_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void loadPushMessages();
        startPolling();
      } else {
        stopPolling();
      }
    };

    if (document.visibilityState === "visible") {
      startPolling();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
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
    const unreadIds = pushMessagesRef.current
      .filter((message) => !message.read)
      .map((m) => m.id);
    // Always call the backend — there may be unread events hidden from the
    // local list (e.g. ACL pending notifications filtered client-side).
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
  }, []);

  const deleteMessages = useCallback(async (messageIds: string[]) => {
    const ids = Array.from(
      new Set(messageIds.map((id) => id.trim()).filter(Boolean)),
    );
    if (!ids.length) return 0;
    const idSet = new Set(ids);
    await Promise.allSettled(ids.map((id) => api.deleteInboxEvent(id)));
    let deleted = 0;
    let unreadDeleted = 0;
    setPushMessages((prev) => {
      const remaining: PushMessage[] = [];
      for (const message of prev) {
        if (idSet.has(message.id)) {
          deleted += 1;
          if (!message.read) unreadDeleted += 1;
          continue;
        }
        remaining.push(message);
      }
      return remaining;
    });
    setSummary((prev) => ({
      ...prev,
      pushMessages: {
        total: Math.max(prev.pushMessages.total - deleted, 0),
        unread: Math.max(prev.pushMessages.unread - unreadDeleted, 0),
      },
    }));
    return deleted;
  }, []);

  const deleteMessage = useCallback(
    (messageId: string) => {
      void deleteMessages([messageId]);
    },
    [deleteMessages],
  );

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
    deleteMessages,
    triggerHarvest,
    refreshPushMessages: loadPushMessages,
  };
};
