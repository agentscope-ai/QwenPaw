import React, { useCallback, useMemo, useState } from "react";
import { Input, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { FixedSizeList, type ListChildComponentProps } from "react-window";
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

// ── Virtual list constants ────────────────────────────────────────────────

/** SidebarSessionItem: padding 8+8 + line-height 20 + margin-bottom 2 = 38px */
const SESSION_ITEM_HEIGHT = 38;

/** Data passed to each row via FixedSizeList's itemData prop */
interface SessionRowData {
  sessions: ExtendedChatSession[];
  currentSessionId: string | undefined;
  editingSessionId: string | null;
  editValue: string;
  t: ReturnType<typeof useTranslation>["t"];
  handleSessionClick: (sessionId: string) => void;
  handleEditStart: (sessionId: string, currentName: string) => void;
  handleDelete: (sessionId: string) => void;
  handlePinToggle: (sessionId: string) => void;
  handleEditChange: (value: string) => void;
  handleEditSubmit: () => void;
  handleEditCancel: () => void;
}

/** Memoized row renderer — only re-renders when its specific props change */
const SessionRow = React.memo(function SessionRow({
  index,
  style,
  data,
}: ListChildComponentProps<SessionRowData>) {
  const session = data.sessions[index];
  if (!session) return null;

  const channelKey = session.channel?.trim() || "";
  const channelLabel = channelKey
    ? getChannelLabel(channelKey, data.t)
    : undefined;
  const isEditing = data.editingSessionId === session.id;

  return (
    <div style={style}>
      <SidebarSessionItem
        sessionId={session.id!}
        name={session.name || "New Chat"}
        channelKey={channelKey || undefined}
        channelLabel={channelLabel}
        chatStatus={session.status}
        generating={session.generating}
        pinned={session.pinned}
        active={
          session.id === data.currentSessionId ||
          (!!data.currentSessionId && session.realId === data.currentSessionId)
        }
        disabled={false}
        editing={isEditing}
        editValue={isEditing ? data.editValue : undefined}
        onClick={data.handleSessionClick}
        onEdit={data.handleEditStart}
        onDelete={data.handleDelete}
        onPin={data.handlePinToggle}
        onEditChange={data.handleEditChange}
        onEditSubmit={data.handleEditSubmit}
        onEditCancel={data.handleEditCancel}
      />
    </div>
  );
});

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
    sortedSessions: allSortedSessions,
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

  // Filter out local temporary sessions (created by clicking "New Chat" but
  // not yet persisted to backend). These sessions have local timestamp IDs
  // (matching /^\d+-[a-z0-9]+$/) and no realId field. They should only appear
  // in the list after the first message is sent and the backend creates them.
  const sortedSessions = useMemo(() => {
    return allSortedSessions.filter((session) => {
      const isLocalId = /^\d+-[a-z0-9]+$/.test(session.id);
      const hasRealId = !!(session as ExtendedChatSession).realId;
      // Keep if: not a local ID, OR has been resolved to a real backend ID
      return !isLocalId || hasRealId;
    });
  }, [allSortedSessions]);

  const handleNewChat = useCallback(() => {
    if (onNewChat) {
      onNewChat();
    } else {
      window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
    }
  }, [onNewChat]);

  // Filter sessions by search query
  const displaySessions = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return sortedSessions;
    return sortedSessions.filter((s) =>
      (s.name || "New Chat").toLowerCase().includes(q),
    );
  }, [sortedSessions, searchQuery]);

  // Stable itemData for FixedSizeList
  const itemData = useMemo<SessionRowData>(
    () => ({
      sessions: displaySessions,
      currentSessionId,
      editingSessionId,
      editValue,
      t,
      handleSessionClick,
      handleEditStart,
      handleDelete,
      handlePinToggle,
      handleEditChange,
      handleEditSubmit,
      handleEditCancel,
    }),
    [
      displaySessions,
      currentSessionId,
      editingSessionId,
      editValue,
      t,
      handleSessionClick,
      handleEditStart,
      handleDelete,
      handlePinToggle,
      handleEditChange,
      handleEditSubmit,
      handleEditCancel,
    ],
  );

  // Measure list container height via ResizeObserver
  const [listHeight, setListHeight] = useState(300);
  const listWrapperRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.height > 0) {
          setListHeight(entry.contentRect.height);
        }
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div className={styles.sessionList}>
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
        <div className={styles.scroll} ref={listWrapperRef}>
          {loading && displaySessions.length === 0 && (
            <div className={styles.loadingState}>
              <Spin size="small" />
            </div>
          )}
          {!loading && displaySessions.length === 0 && (
            <div className={styles.emptyState}>
              {t("chat.sessionPanel.noConversations", "No conversations")}
            </div>
          )}
          {displaySessions.length > 0 && (
            <FixedSizeList
              height={listHeight}
              width="100%"
              itemCount={displaySessions.length}
              itemSize={SESSION_ITEM_HEIGHT}
              overscanCount={10}
              itemData={itemData}
            >
              {SessionRow}
            </FixedSizeList>
          )}
        </div>
      )}
    </div>
  );
}
