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
  INBOX_CHANGED_EVENT,
  notifyInboxChanged,
  type InboxChange,
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

const getHeartbeatSummary = (
  status: string | undefined,
  t: TFunction,
): string => {
  const normalizedStatus = (status || "").toLowerCase();
  if (normalizedStatus === "success") {
    return t("inbox.heartbeatSuccess");
  }
  if (normalizedStatus === "timeout") {
    return t("inbox.heartbeatTimeout");
  }
  if (normalizedStatus === "cancelled") {
    return t("inbox.heartbeatCancelled");
  }
  return t("inbox.heartbeatFailed");
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
    case "community":
      return "community";
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
    case "community":
      return t("communityFeedback.community");
    default:
      return "System";
  }
};

const mapEventToPushMessage = (
  event: InboxEvent,
  resolveAgentName: (agentId: string) => string,
  t: TFunction,
): PushMessage => {
  const isCommunity = event.source_type === "community";
  const communitySender =
    isCommunity &&
    event.payload?.sender &&
    typeof event.payload.sender === "object"
      ? (event.payload.sender as Record<string, unknown>)
      : {};
  const isSkillAutomation = event.source_type === "skill_autoupdate";
  const isBuiltinUpdate = isSkillAutomation && isBuiltinAutoUpdateEvent(event);
  let title = event.title;
  let content = isCommunity ? event.body : stripExecutionTimeText(event.body);
  if (event.source_type === "heartbeat") {
    content = getHeartbeatSummary(event.status, t);
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
      userId: isCommunity
        ? typeof communitySender.id === "string"
          ? communitySender.id
          : ""
        : event.agent_id || "default",
      username: isCommunity
        ? typeof communitySender.name === "string" &&
          communitySender.name.trim()
          ? communitySender.name
          : t("communityInbox.unknownSender")
        : isSkillAutomation
        ? t("inbox.skillPoolSender")
        : resolveAgentName(event.agent_id || DEFAULT_AGENT_ID),
      avatarUrl:
        isCommunity &&
        typeof communitySender.avatar_url === "string" &&
        /^https:\/\//.test(communitySender.avatar_url)
          ? communitySender.avatar_url
          : undefined,
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
      agentId: isCommunity ? undefined : event.agent_id,
      payload:
        event.payload && typeof event.payload === "object"
          ? event.payload
          : undefined,
    },
  };
};

export interface InboxDataOptions {
  sourceType?: string;
  agentId?: string;
  page?: number;
  pageSize?: number;
}

export const useInboxData = ({
  sourceType,
  agentId,
  page = 1,
  pageSize = 20,
}: InboxDataOptions = {}) => {
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

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const readingIds = useRef(new Set<string>());
  const effectiveAgentId = sourceType === "community" ? undefined : agentId;
  const queryKey = JSON.stringify([
    sourceType,
    effectiveAgentId,
    page,
    pageSize,
  ]);
  const queryKeyRef = useRef(queryKey);
  queryKeyRef.current = queryKey;

  const loadPushMessages = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    try {
      const res = await api.getInboxEvents({
        limit: pageSize,
        offset: (Math.max(1, page) - 1) * pageSize,
        source_types: sourceType ? [sourceType] : [...PUSH_MESSAGE_SOURCES],
        agent_id: effectiveAgentId,
        exclude_acl_pending: true,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      const events = [...(res?.events || [])].filter(
        (event) =>
          isPushMessageEvent(event) && event.payload?.acl_status !== "pending",
      );
      events.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
      const nextItems = events.map((event) =>
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
      // A source can fail independently while local messages remain readable.
      setError(res?.source_errors?.community || null);
    } catch (error) {
      if (!controller.signal.aborted) {
        console.error("Failed to fetch push inbox data", error);
        setError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
  }, [sourceType, effectiveAgentId, page, pageSize]);

  useEffect(() => {
    // A different query must not display messages from the previous account or
    // source while it is loading. Poll failures retain the current query's data.
    setPushMessages([]);
    void loadPushMessages();
    let timer: number | null = null;
    const startPolling = () => {
      if (timer == null)
        timer = window.setInterval(
          () => void loadPushMessages(),
          PUSH_POLLING_INTERVAL_MS,
        );
    };
    const stopPolling = () => {
      if (timer != null) {
        window.clearInterval(timer);
        timer = null;
      }
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void loadPushMessages();
        startPolling();
      } else stopPolling();
    };
    const onInboxChanged = (event: Event) => {
      const change = (event as CustomEvent<InboxChange>).detail;
      if (change?.clearSources?.length) {
        setPushMessages((items) =>
          items.filter(
            (item) =>
              !change.clearSources!.includes(item.metadata?.sourceType || ""),
          ),
        );
        if (sourceType && change.clearSources.includes(sourceType))
          setSummary((prev) => ({
            ...prev,
            pushMessages: { total: 0, unread: 0 },
          }));
      }
      void loadPushMessages();
    };
    if (document.visibilityState === "visible") startPolling();
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener(INBOX_CHANGED_EVENT, onInboxChanged);
    return () => {
      requestRef.current?.abort();
      stopPolling();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener(INBOX_CHANGED_EVENT, onInboxChanged);
    };
  }, [loadPushMessages, sourceType]);

  const markMessageAsRead = useCallback((messageId: string) => {
    const item = pushMessagesRef.current.find(
      (message) => message.id === messageId,
    );
    if (!item || item.read || readingIds.current.has(messageId)) return;
    const targetQuery = queryKeyRef.current;
    readingIds.current.add(messageId);
    void api
      .markInboxRead({ event_ids: [messageId] })
      .then(() => {
        if (queryKeyRef.current === targetQuery) {
          setPushMessages((prev) =>
            prev.map((message) =>
              message.id === messageId ? { ...message, read: true } : message,
            ),
          );
          setSummary((prev) => ({
            ...prev,
            pushMessages: {
              ...prev.pushMessages,
              unread: Math.max(0, prev.pushMessages.unread - 1),
            },
          }));
        }
        notifyInboxChanged({ readIds: [messageId] });
      })
      .catch((error) => {
        setError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => readingIds.current.delete(messageId));
  }, []);

  const markAllMessagesAsRead = useCallback(async (): Promise<number> => {
    const targetQuery = queryKeyRef.current;
    const unreadCount = summary.pushMessages.unread;
    const result = await api.markInboxRead({
      all: true,
      ...(sourceType ? { source_types: [sourceType] } : {}),
      ...(effectiveAgentId ? { agent_id: effectiveAgentId } : {}),
    });
    if (queryKeyRef.current === targetQuery) {
      setPushMessages((prev) =>
        prev.map((message) => ({ ...message, read: true })),
      );
      setSummary((prev) => ({
        ...prev,
        pushMessages: { ...prev.pushMessages, unread: 0 },
      }));
    }
    notifyInboxChanged({
      readAll: true,
      sourceTypes: sourceType ? [sourceType] : undefined,
      agentId: effectiveAgentId,
    });
    return result?.updated ?? unreadCount;
  }, [sourceType, effectiveAgentId, summary.pushMessages.unread]);

  const deleteMessages = useCallback(async (messageIds: string[]) => {
    const targetQuery = queryKeyRef.current;
    const ids = [...new Set(messageIds.map((id) => id.trim()).filter(Boolean))];
    if (!ids.length) return 0;
    const results = await Promise.allSettled(
      ids.map((id) => api.deleteInboxEvent(id)),
    );
    const deletedIds = ids.filter(
      (_, index) => results[index].status === "fulfilled",
    );
    const idSet = new Set(deletedIds);
    const unreadDeleted = pushMessagesRef.current.filter(
      (message) => idSet.has(message.id) && !message.read,
    ).length;
    if (queryKeyRef.current === targetQuery) {
      setPushMessages((prev) =>
        prev.filter((message) => !idSet.has(message.id)),
      );
      setSummary((prev) => ({
        ...prev,
        pushMessages: {
          total: Math.max(0, prev.pushMessages.total - deletedIds.length),
          unread: Math.max(0, prev.pushMessages.unread - unreadDeleted),
        },
      }));
    }
    if (deletedIds.length !== ids.length)
      setError(tRef.current("communityInbox.deleteFailed"));
    if (deletedIds.length) notifyInboxChanged({ deletedIds });
    return deletedIds.length;
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
    loading,
    error,
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
