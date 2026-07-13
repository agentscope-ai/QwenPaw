import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Input, Spin } from "antd";
import { VariableSizeList, type ListChildComponentProps } from "react-window";
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
import SessionItem from "../components/SessionItem";
import styles from "./sidebarSessionList.module.less";

/** Fixed height of each session item row */
const SESSION_ROW_HEIGHT = 42;
/** Fixed height of each group header row */
const GROUP_HEADER_HEIGHT = 28;

/** A flattened row: either a group header or a session item */
type FlatRow =
  | {
      kind: "groupHeader";
      groupKey: DateGroup;
      label: string;
      count: number;
      collapsed: boolean;
    }
  | { kind: "session"; session: ExtendedChatSession };

// ── Component ─────────────────────────────────────────────────────────────

/** Data passed to each virtual row */
interface VirtualRowData {
  flatRows: FlatRow[];
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
  toggleGroup: (key: DateGroup) => void;
}

/** Virtual list row renderer */
const VirtualRow = React.memo(function VirtualRow({
  index,
  style,
  data,
}: ListChildComponentProps<VirtualRowData>) {
  const row = data.flatRows[index];
  if (!row) return null;

  if (row.kind === "groupHeader") {
    return (
      <div style={style}>
        <button
          className={styles.groupLabel}
          onClick={() => data.toggleGroup(row.groupKey)}
        >
          <span>{row.label}</span>
          <span
            className={styles.groupChevron}
            style={{
              transform: row.collapsed ? "rotate(-90deg)" : "rotate(0deg)",
            }}
          >
            <SparkDownArrowLine size={10} />
          </span>
        </button>
      </div>
    );
  }

  const session = row.session;
  const channelKey = session.channel?.trim() || "";
  const channelLabel = channelKey
    ? getChannelLabel(channelKey, data.t)
    : undefined;
  const isEditing = data.editingSessionId === session.id;

  return (
    <div style={style}>
      <SessionItem
        variant="sidebar"
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

  /** Flatten groups into a single array of rows for virtual list */
  const flatRows = useMemo<FlatRow[]>(() => {
    if (searchQuery.trim()) {
      return filteredSessions.map((s) => ({
        kind: "session",
        session: s,
      }));
    }
    if (!groups) return [];
    const rows: FlatRow[] = [];
    for (const group of groups) {
      const collapsed = collapsedGroups.has(group.key);
      rows.push({
        kind: "groupHeader",
        groupKey: group.key,
        label: group.label,
        count: group.sessions.length,
        collapsed,
      });
      if (!collapsed) {
        for (const session of group.sessions) {
          rows.push({ kind: "session", session });
        }
      }
    }
    return rows;
  }, [groups, collapsedGroups, searchQuery, filteredSessions]);

  /** Row height calculator for VariableSizeList */
  const getRowHeight = useCallback(
    (index: number) => {
      const row = flatRows[index];
      if (!row) return SESSION_ROW_HEIGHT;
      return row.kind === "groupHeader"
        ? GROUP_HEADER_HEIGHT
        : SESSION_ROW_HEIGHT;
    },
    [flatRows],
  );

  /** Height of the virtual list container */
  const [listHeight, setListHeight] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);
  const listRef = useRef<VariableSizeList>(null);

  /** Reset virtual list cache when flatRows change */
  useEffect(() => {
    listRef.current?.resetAfterIndex(0);
  }, [flatRows]);

  /** Callback ref: attach a ResizeObserver to measure list container height */
  const listWrapperRef = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const height = entry.contentRect.height;
        if (height > 0) setListHeight(height);
      }
    });
    observer.observe(node);
    observerRef.current = observer;
    const initialHeight = node.clientHeight;
    if (initialHeight > 0) setListHeight(initialHeight);
  }, []);

  /** Data passed to each virtual row */
  const virtualListData = useMemo(
    () => ({
      flatRows,
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
      toggleGroup,
    }),
    [
      flatRows,
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
      toggleGroup,
    ],
  );

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
        <div className={styles.scroll} ref={listWrapperRef}>
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

          {sortedSessions.length > 0 && listHeight > 0 && (
            <VariableSizeList
              ref={listRef}
              height={listHeight}
              width="100%"
              itemCount={flatRows.length}
              itemSize={getRowHeight}
              itemData={virtualListData}
              className={styles.list}
              overscanCount={10}
            >
              {VirtualRow}
            </VariableSizeList>
          )}
        </div>
      )}
    </div>
  );
}
