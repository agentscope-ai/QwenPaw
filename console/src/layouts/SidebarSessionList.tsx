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
import { type DateGroup, groupSessions } from "../utils/sessionGrouping";
import SidebarSessionItem from "./SidebarSessionItem";
import styles from "./sidebarSessionList.module.less";

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
  /** Collapsed date groups — default: "month" and "older" are collapsed */
  const [collapsedGroups, setCollapsedGroups] = useState<Set<DateGroup>>(
    () => new Set<DateGroup>(["month", "older"]),
  );

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

  const toggleGroup = useCallback((key: DateGroup) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const renderItem = (session: ExtendedChatSession) => {
    const channelKey = session.channel?.trim() || "";
    const channelLabel = channelKey
      ? getChannelLabel(channelKey, t)
      : undefined;
    const isEditing = editingSessionId === session.id;

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
        active={
          session.id === currentSessionId ||
          (!!currentSessionId && session.realId === currentSessionId)
        }
        disabled={false}
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
    <div className={styles.sessionList}>
      {/* Sticky header: new chat + history title + search */}
      <div className={styles.sessionListHeader}>
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
              placeholder={t(
                "chat.sessionPanel.searchConversations",
                "Search…",
              )}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={styles.searchInput}
            />
          </div>
        )}
      </div>

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
            : /* Grouped by date with collapsible headers */
              groups?.map((group) => {
                const isCollapsed = collapsedGroups.has(group.key);
                return (
                  <div key={group.key} className={styles.group}>
                    <button
                      className={styles.groupLabel}
                      onClick={() => toggleGroup(group.key)}
                    >
                      <span>{group.label}</span>
                      <span
                        className={styles.groupChevron}
                        style={{
                          transform: isCollapsed
                            ? "rotate(-90deg)"
                            : "rotate(0deg)",
                        }}
                      >
                        <SparkDownArrowLine size={10} />
                      </span>
                    </button>
                    {!isCollapsed && group.sessions.map(renderItem)}
                  </div>
                );
              })}
        </div>
      )}
    </div>
  );
}
