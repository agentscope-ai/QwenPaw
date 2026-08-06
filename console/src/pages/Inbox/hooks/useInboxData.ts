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
const TRASH_RETENTION_DAYS = 30;
const LS_ARCHIVED_KEY = "qwenpaw.inbox.archived";
const LS_TRASHED_KEY = "qwenpaw.inbox.trashed";

const MOCK_HARVESTS: HarvestInstance[] = [];

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

interface IdMap {
  [messageId: string]: number;
}

const readIdMap = (key: string): IdMap => {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) return parsed as IdMap;
    return {};
  } catch {
    return {};
  }
};

const writeIdMap = (key: string, map: IdMap): void => {
  try {
    localStorage.setItem(key, JSON.stringify(map));
  } catch {
    // localStorage quota exceeded — silently ignore
  }
};

/** Remove entries whose IDs are no longer present in the given set. */
const pruneIdMap = (map: IdMap, validIds: Set<string>): IdMap => {
  const next: IdMap = {};
  for (const id of Object.keys(map)) {
    if (validIds.has(id)) next[id] = map[id];
  }
  return next;
};

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

const getSkillAutoUpdateSummary = (event: InboxEvent, t: TFunction): string => {
  const payload = (event.payload || {}) as {
    synced?: { skill?: string; agents?: string[] }[];
    failed?: { skill?: string; agents?: string[] }[];
  };
  const parts: string[] = [];
  for (const item of payload.synced || []) {
    parts.push(
      t("inbox.skillAutoUpdated", {
        skill: item.skill,
        agents: (item.agents || []).join(", "),
      }),
    );
  }
  for (const item of payload.failed || []) {
    parts.push(
      t("inbox.skillAutoUpdateFailed", {
        skill: item.skill,
        agents: (item.agents || []).join(", "),
      }),
    );
  }
  return parts.join("; ") || event.body;
};

const mapEventToPushMessage = (
  event: InboxEvent,
  resolveAgentName: (agentId: string) => string,
  t: TFunction,
): PushMessage => ({
  id: event.id,
  channelType:
    event.source_type === "heartbeat"
      ? "heartbeat"
      : event.source_type === "memory"
      ? "memory"
      : event.source_type === "cron"
      ? "wechat"
      : event.source_type === "skill_autoupdate"
      ? "skill"
      : "email",
  channelName:
    event.source_type === "heartbeat"
      ? "Heartbeat"
      : event.source_type === "memory"
      ? "Memory"
      : event.source_type === "cron"
      ? "Cron"
      : event.source_type === "skill_autoupdate"
      ? "Auto Sync"
      : "System",
  title:
    event.source_type === "skill_autoupdate"
      ? t("inbox.skillAutoUpdateTitle")
      : event.title,
  content:
    event.source_type === "heartbeat"
      ? getHeartbeatSummary(event.status)
      : event.source_type === "skill_autoupdate"
      ? getSkillAutoUpdateSummary(event, t)
      : stripExecutionTimeText(event.body),
  sender: {
    userId: event.agent_id || "default",
    username:
      event.source_type === "skill_autoupdate"
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
});

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
  const [archivedMap, setArchivedMap] = useState<IdMap>(() =>
    readIdMap(LS_ARCHIVED_KEY),
  );
  const [trashedMap, setTrashedMap] = useState<IdMap>(() =>
    readIdMap(LS_TRASHED_KEY),
  );

  // Keep localStorage in sync with state
  const persistArchived = useCallback((map: IdMap) => {
    setArchivedMap(map);
    writeIdMap(LS_ARCHIVED_KEY, map);
  }, []);
  const persistTrashed = useCallback((map: IdMap) => {
    setTrashedMap(map);
    writeIdMap(LS_TRASHED_KEY, map);
  }, []);

  /** Clean up trashed items older than TRASH_RETENTION_DAYS. */
  const cleanExpiredTrash = useCallback(async (map: IdMap): Promise<IdMap> => {
    const cutoff = Date.now() - TRASH_RETENTION_DAYS * 24 * 60 * 60 * 1000;
    const expired: string[] = [];
    const remaining: IdMap = {};
    for (const [id, ts] of Object.entries(map)) {
      if (ts < cutoff) {
        expired.push(id);
      } else {
        remaining[id] = ts;
      }
    }
    if (expired.length > 0) {
      await Promise.allSettled(expired.map((id) => api.deleteInboxEvent(id)));
      writeIdMap(LS_TRASHED_KEY, remaining);
    }
    return remaining;
  }, []);

  const loadPushMessages = useCallback(async () => {
    try {
      // Clean expired trash first.
      const currentTrashed = readIdMap(LS_TRASHED_KEY);
      const cleanedTrash = await cleanExpiredTrash(currentTrashed);
      setTrashedMap(cleanedTrash);

      const res = await api.getInboxEvents({
        limit: INBOX_EVENT_QUERY_LIMIT,
        source_types: [...PUSH_MESSAGE_SOURCES],
      });
      const events = [...(res?.events || [])].filter(isPushMessageEvent);
      events.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

      // Prune stale entries from localStorage maps
      const validIds = new Set(events.map((e) => e.id));
      const prunedArchived = pruneIdMap(readIdMap(LS_ARCHIVED_KEY), validIds);
      const prunedTrashed = pruneIdMap(cleanedTrash, validIds);
      writeIdMap(LS_ARCHIVED_KEY, prunedArchived);
      writeIdMap(LS_TRASHED_KEY, prunedTrashed);
      setArchivedMap(prunedArchived);
      setTrashedMap(prunedTrashed);

      const archivedIdSet = new Set(Object.keys(prunedArchived));
      const trashedIdSet = new Set(Object.keys(prunedTrashed));

      const nextItems: PushMessage[] = events
        .map((event) =>
          mapEventToPushMessage(
            event,
            resolveAgentNameRef.current,
            tRef.current,
          ),
        )
        .map((msg) => ({
          ...msg,
          archived: archivedIdSet.has(msg.id),
          archivedAt: prunedArchived[msg.id],
          trashed: trashedIdSet.has(msg.id),
          trashedAt: prunedTrashed[msg.id],
        }));

      setPushMessages(nextItems);
      const activeMessages = nextItems.filter((m) => !m.archived && !m.trashed);
      setSummary((prev) => ({
        ...prev,
        pushMessages: {
          total: activeMessages.length,
          unread: activeMessages.filter((m) => !m.read).length,
        },
      }));
    } catch (error) {
      console.error("Failed to fetch push inbox data", error);
    }
  }, [cleanExpiredTrash]);

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

  // ── Archive ────────────────────────────────────────────────────────────

  const archiveMessages = useCallback(
    (ids: string[]) => {
      const now = Date.now();
      const next = { ...archivedMap };
      for (const id of ids) next[id] = now;
      persistArchived(next);
      setPushMessages((prev) =>
        prev.map((m) =>
          ids.includes(m.id) ? { ...m, archived: true, archivedAt: now } : m,
        ),
      );
      setSummary((prev) => {
        const active = pushMessagesRef.current.filter(
          (m) => !ids.includes(m.id) && !m.trashed,
        );
        return {
          ...prev,
          pushMessages: {
            total: active.length,
            unread: active.filter((m) => !m.read).length,
          },
        };
      });
    },
    [archivedMap, persistArchived],
  );

  const archiveMessage = useCallback(
    (messageId: string) => archiveMessages([messageId]),
    [archiveMessages],
  );

  // ── Trash ──────────────────────────────────────────────────────────────

  const trashMessages = useCallback(
    (ids: string[]) => {
      const now = Date.now();
      const nextTrash = { ...trashedMap };
      for (const id of ids) nextTrash[id] = now;
      persistTrashed(nextTrash);
      // Also remove from archive if present
      const nextArchive = { ...archivedMap };
      let archiveChanged = false;
      for (const id of ids) {
        if (nextArchive[id] !== undefined) {
          delete nextArchive[id];
          archiveChanged = true;
        }
      }
      if (archiveChanged) persistArchived(nextArchive);
      setPushMessages((prev) =>
        prev.map((m) =>
          ids.includes(m.id)
            ? {
                ...m,
                trashed: true,
                trashedAt: now,
                archived: false,
                archivedAt: undefined,
              }
            : m,
        ),
      );
      setSummary((prev) => {
        const active = pushMessagesRef.current.filter(
          (m) => !ids.includes(m.id) && !m.archived,
        );
        return {
          ...prev,
          pushMessages: {
            total: active.length,
            unread: active.filter((m) => !m.read).length,
          },
        };
      });
    },
    [archivedMap, trashedMap, persistArchived, persistTrashed],
  );

  const trashMessage = useCallback(
    (messageId: string) => trashMessages([messageId]),
    [trashMessages],
  );

  // ── Restore ────────────────────────────────────────────────────────────

  const restoreMessages = useCallback(
    (ids: string[]) => {
      const nextArchive = { ...archivedMap };
      const nextTrash = { ...trashedMap };
      for (const id of ids) {
        delete nextArchive[id];
        delete nextTrash[id];
      }
      persistArchived(nextArchive);
      persistTrashed(nextTrash);
      setPushMessages((prev) =>
        prev.map((m) =>
          ids.includes(m.id)
            ? {
                ...m,
                archived: false,
                archivedAt: undefined,
                trashed: false,
                trashedAt: undefined,
              }
            : m,
        ),
      );
      setSummary((prev) => {
        const active = pushMessagesRef.current.filter(
          (m) => !ids.includes(m.id) && !m.archived && !m.trashed,
        );
        const newlyActive = ids.filter((id) => {
          const msg = pushMessagesRef.current.find((m) => m.id === id);
          return msg && !msg.read;
        }).length;
        return {
          ...prev,
          pushMessages: {
            total: active.length + ids.length,
            unread: Math.max(
              0,
              active.filter((m) => !m.read).length + newlyActive,
            ),
          },
        };
      });
    },
    [archivedMap, trashedMap, persistArchived, persistTrashed],
  );

  const restoreMessage = useCallback(
    (messageId: string) => restoreMessages([messageId]),
    [restoreMessages],
  );

  // ── Permanent delete ───────────────────────────────────────────────────

  const permanentlyDeleteMessages = useCallback(
    async (ids: string[]) => {
      const idSet = new Set(ids);
      await Promise.allSettled(ids.map((id) => api.deleteInboxEvent(id)));
      const nextTrash = { ...trashedMap };
      for (const id of ids) delete nextTrash[id];
      persistTrashed(nextTrash);
      setPushMessages((prev) => prev.filter((m) => !idSet.has(m.id)));
    },
    [trashedMap, persistTrashed],
  );

  const emptyTrash = useCallback(async () => {
    const ids = Object.keys(trashedMap);
    if (ids.length === 0) return;
    await Promise.allSettled(ids.map((id) => api.deleteInboxEvent(id)));
    persistTrashed({});
    setPushMessages((prev) => prev.filter((m) => !m.trashed));
  }, [trashedMap, persistTrashed]);

  // ── Computed message lists ─────────────────────────────────────────────

  const activeMessages = useMemo(
    () => pushMessages.filter((m) => !m.archived && !m.trashed),
    [pushMessages],
  );

  const archivedMessages = useMemo(
    () => pushMessages.filter((m) => m.archived && !m.trashed),
    [pushMessages],
  );

  const trashedMessages = useMemo(
    () => pushMessages.filter((m) => m.trashed),
    [pushMessages],
  );

  const triggerHarvest = useCallback((harvestId: string) => {
    console.info("triggerHarvest", harvestId);
  }, []);

  return {
    summary,
    pushMessages: activeMessages,
    archivedMessages,
    trashedMessages,
    harvests,
    markMessageAsRead,
    markAllMessagesAsRead,
    deleteMessage,
    deleteMessages,
    archiveMessage,
    archiveMessages,
    trashMessage,
    trashMessages,
    restoreMessage,
    restoreMessages,
    permanentlyDeleteMessages,
    emptyTrash,
    triggerHarvest,
    refreshPushMessages: loadPushMessages,
  };
};
