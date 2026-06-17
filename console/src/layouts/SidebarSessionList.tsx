import { useCallback, useMemo, useState } from "react";
import { Input, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { SparkPlusLine, SparkDownArrowLine } from "@agentscope-ai/icons";
import { getChannelLabel } from "../pages/Control/Channels/components";
import {
  useSessionListData,
  type ExtendedChatSession,
} from "../pages/Chat/components/ChatSessionDrawer/useSessionListData";
import { getSessionIdFromPath } from "../utils/sessionRoute";
import {
  useSessionListStore,
  syncSessionsGlobal,
  type ExtendedSession,
} from "../stores/sessionListStore";
import SidebarSessionItem from "./SidebarSessionItem";
import styles from "./sidebarSessionList.module.less";

// ── Date grouping ─────────────────────────────────────────────────────────

type DateGroup = "pinned" | "today" | "week" | "month" | "older";

interface SessionGroup {
  key: DateGroup;
  label: string;
  sessions: ExtendedChatSession[];
}

function getDateGroup(
  timestamp: string | null | undefined,
): Exclude<DateGroup, "pinned"> {
  if (!timestamp) return "older";
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return "older";

  // Use calendar dates (not elapsed-time differences) so that
  // "today" always means the same Y/M/D, regardless of the hour.
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dateStart = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );
  const calendarDays = Math.floor(
    (todayStart.getTime() - dateStart.getTime()) / (1000 * 60 * 60 * 24),
  );

  if (calendarDays <= 0) return "today"; // same calendar day (or future)
  if (calendarDays < 7) return "week";
  if (calendarDays < 30) return "month";
  return "older";
}

function groupSessions(
  sessions: ExtendedChatSession[],
  t: (key: string, fallback: string) => string,
): SessionGroup[] {
  const buckets: Record<DateGroup, ExtendedChatSession[]> = {
    pinned: [],
    today: [],
    week: [],
    month: [],
    older: [],
  };

  for (const s of sessions) {
    if (s.pinned) {
      buckets.pinned.push(s);
    } else {
      buckets[getDateGroup(s.updatedAt ?? s.createdAt)].push(s);
    }
  }

  const order: Array<{ key: DateGroup; fallback: string }> = [
    { key: "pinned", fallback: "Pinned" },
    { key: "today", fallback: "Today" },
    { key: "week", fallback: "Within 7 days" },
    { key: "month", fallback: "Within 30 days" },
    { key: "older", fallback: "Earlier" },
  ];

  return order
    .filter(({ key }) => buckets[key].length > 0)
    .map(({ key, fallback }) => ({
      key,
      label: t(`chat.group.${key}`, fallback),
      sessions: buckets[key],
    }));
}

// ── Component ─────────────────────────────────────────────────────────────

export interface SidebarSessionListProps {
  /** Called when user clicks "New Chat". Provided by parent (Sidebar) which has navigate(). */
  onNewChat?: () => void;
  /** Called when user clicks a session. Provided by parent for direct navigation. */
  onSessionClick?: (sessionId: string) => void;
}

export default function SidebarSessionList({
  onNewChat,
  onSessionClick: onSessionClickProp,
}: SidebarSessionListProps = {}) {
  const { t } = useTranslation();
  const location = useLocation();
  const currentSessionId = getSessionIdFromPath(location.pathname) ?? undefined;

  const [searchQuery, setSearchQuery] = useState("");
  const [historyCollapsed, setHistoryCollapsed] = useState(false);

  const storeSessionsRaw = useSessionListStore((s) => s.sessions);
  const storeSessions = storeSessionsRaw as ExtendedChatSession[];

  const setSessions = useCallback((sessions: ExtendedChatSession[]) => {
    syncSessionsGlobal(sessions as ExtendedSession[]);
  }, []);

  /**
   * Session click: prefer injected callback (direct navigate from Sidebar),
   * fall back to DOM event for backward compat when used standalone.
   */
  const onSessionClick = useCallback(
    (sessionId: string) => {
      if (onSessionClickProp) {
        onSessionClickProp(sessionId);
      } else {
        window.dispatchEvent(
          new CustomEvent("qwenpaw:sidebar-select-session", {
            detail: { sessionId },
          }),
        );
      }
    },
    [onSessionClickProp],
  );

  const {
    sortedSessions,
    loading,
    switchingSessionId,
    editingSessionId,
    editValue,
    handleSessionClick,
    handleEditStart,
    handleDelete,
    handlePinToggle,
    handleEditChange,
    handleEditSubmit,
    handleEditCancel,
  } = useSessionListData(storeSessions, setSessions, {
    active: true,
    currentSessionId,
    onSessionClick,
  });

  const handleNewChat = useCallback(() => {
    if (onNewChat) {
      onNewChat();
    } else {
      window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
    }
  }, [onNewChat]);

  // Filter sessions by search query
  const filteredSessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return sortedSessions;
    return sortedSessions.filter((s) =>
      (s.name || "New Chat").toLowerCase().includes(q),
    );
  }, [sortedSessions, searchQuery]);

  const groups = useMemo(
    () => (searchQuery.trim() ? null : groupSessions(sortedSessions, t)),
    [sortedSessions, searchQuery, t],
  );

  const renderItem = (session: ExtendedChatSession) => {
    const channelKey = session.channel?.trim() || "";
    const channelLabel = channelKey
      ? getChannelLabel(channelKey, t)
      : undefined;
    const isEditing = editingSessionId === session.id;
    const isDisabled =
      !!switchingSessionId && session.id !== switchingSessionId;

    return (
      <SidebarSessionItem
        key={session.id}
        sessionId={session.id!}
        name={session.name || "New Chat"}
        channelKey={channelKey || undefined}
        channelLabel={channelLabel}
        chatStatus={session.status}
        generating={session.generating}
        pinned={session.pinned}
        active={session.id === currentSessionId}
        disabled={isDisabled}
        editing={isEditing}
        editValue={isEditing ? editValue : undefined}
        onClick={handleSessionClick}
        onEdit={handleEditStart}
        onDelete={handleDelete}
        onPin={handlePinToggle}
        onEditChange={handleEditChange}
        onEditSubmit={handleEditSubmit}
        onEditCancel={handleEditCancel}
      />
    );
  };

  return (
    <div
      className={styles.sessionList}
      style={switchingSessionId ? { pointerEvents: "none" } : undefined}
    >
      {/* New Chat button */}
      <button className={styles.newChatBtn} onClick={handleNewChat}>
        <SparkPlusLine size={14} />
        <span>{t("chat.newChatTooltip")}</span>
      </button>

      {/* Conversation history header (collapsible) */}
      <button
        className={styles.historyHeader}
        onClick={() => setHistoryCollapsed((c) => !c)}
      >
        <span className={styles.historyLabel}>
          {t("chat.conversationHistory", "Conversation History")}
        </span>
        <span
          className={styles.historyChevron}
          style={{
            transform: historyCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
          }}
        >
          <SparkDownArrowLine size={12} />
        </span>
      </button>

      {/* Search bar */}
      {!historyCollapsed && (
        <div className={styles.searchContainer}>
          <Input
            size="small"
            allowClear
            placeholder={t("chat.sessionPanel.searchConversations", "Search…")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInput}
          />
        </div>
      )}

      {/* Session list */}
      {!historyCollapsed && (
        <div className={styles.scroll}>
          {loading && sortedSessions.length === 0 && (
            <div className={styles.loadingState}>
              <Spin size="small" />
            </div>
          )}
          {!loading && sortedSessions.length === 0 && (
            <div className={styles.emptyState}>
              {t("chat.sessionPanel.noConversations", "No conversations")}
            </div>
          )}

          {/* Search results — flat list */}
          {searchQuery.trim()
            ? filteredSessions.map(renderItem)
            : /* Grouped by date */
              groups?.map((group) => (
                <div key={group.key} className={styles.group}>
                  <div className={styles.groupLabel}>{group.label}</div>
                  {group.sessions.map(renderItem)}
                </div>
              ))}
        </div>
      )}
    </div>
  );
}
