import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Input, Modal, Spin } from "antd";
import { VariableSizeList, type ListChildComponentProps } from "react-window";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { ChevronDown, FolderPlus, Plus } from "lucide-react";
import { getChannelLabel } from "../pages/Control/Channels/components";
import {
  getBackendId,
  useSessionListData,
  type ExtendedChatSession,
} from "../pages/Chat/components/ChatSessionDrawer/useSessionListData";
import { getSessionIdFromPath } from "../utils/sessionRoute";
import {
  useSessionListStore,
  syncSessionsGlobal,
  type ExtendedSession,
} from "../stores/sessionListStore";
import { findSessionRowIndex } from "../utils/sessionGrouping";
import {
  groupChats,
  groupChatsByDate,
  findStickyGroupHeaderIndex,
  localizeSystemGroups,
  resolveChatGroupId,
  type ChatDateGroup,
} from "../utils/chatGroups";
import { useCollapsedChatGroups } from "../hooks/useCollapsedChatGroups";
import { useRevealActiveChatGroup } from "../hooks/useRevealActiveChatGroup";
import { useChatGroups } from "../hooks/useChatGroups";
import SessionItem from "../components/SessionItem";
import SessionGroupHeader from "../components/SessionGroupHeader";
import SessionDateHeader from "../components/SessionDateHeader";
import {
  DraggableSession,
  SessionDropZone,
  SessionGroupDndProvider,
} from "../components/SessionGroupDnd";
import { chatApi } from "../api/modules/chat";
import type { ChatGroup } from "../api/types/chat";
import { useAppMessage } from "../hooks/useAppMessage";
import styles from "./sidebarSessionList.module.less";

/** Fixed height of each session item row */
const SESSION_ROW_HEIGHT = 42;
/** Fixed height of each group header row */
const GROUP_HEADER_HEIGHT = 42;
const DATE_HEADER_HEIGHT = 24;

/** A flattened row: either a group header or a session item */
type FlatRow =
  | {
      kind: "groupHeader";
      group: ChatGroup;
      count: number;
      collapsed: boolean;
    }
  | {
      kind: "dateHeader";
      groupId: string;
      dateGroup: ChatDateGroup;
      label: string;
    }
  | { kind: "session"; session: ExtendedChatSession; groupId: string };

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
  handleArchiveToggle: (sessionId: string) => void;
  handlePinToggle: (sessionId: string, pinned: boolean) => void;
  handleMove: (sessionId: string, groupId: string) => void;
  handleEditChange: (value: string) => void;
  handleEditSubmit: () => void;
  handleEditCancel: () => void;
  groups: ChatGroup[];
  toggleGroup: (key: string) => void;
  renameGroup: (groupId: string, name: string) => void;
  pinGroup: (groupId: string, pinned: boolean) => void;
  deleteGroup: (groupId: string) => void;
  moveGroup: (groupId: string, offset: number) => void;
}

type GroupHeaderRow = Extract<FlatRow, { kind: "groupHeader" }>;

function GroupHeaderContent({
  row,
  data,
}: {
  row: GroupHeaderRow;
  data: VirtualRowData;
}) {
  const movableGroups = data.groups.filter(
    (group) =>
      group.kind !== "cron" &&
      group.kind !== "subagents" &&
      group.pinned === row.group.pinned,
  );
  const groupIndex = movableGroups.findIndex(
    (group) => group.id === row.group.id,
  );
  return (
    <SessionGroupHeader
      group={row.group}
      count={row.count}
      collapsed={row.collapsed}
      canMoveUp={groupIndex > 0}
      canMoveDown={groupIndex >= 0 && groupIndex < movableGroups.length - 1}
      onToggle={() => data.toggleGroup(row.group.id)}
      onRename={(name) => data.renameGroup(row.group.id, name)}
      onPin={(pinned) => data.pinGroup(row.group.id, pinned)}
      onDelete={() => data.deleteGroup(row.group.id)}
      onMoveUp={() => data.moveGroup(row.group.id, -1)}
      onMoveDown={() => data.moveGroup(row.group.id, 1)}
    />
  );
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
      <SessionDropZone
        id={`group:${row.group.id}`}
        groupId={row.group.id}
        style={style}
      >
        <GroupHeaderContent row={row} data={data} />
      </SessionDropZone>
    );
  }

  if (row.kind === "dateHeader") {
    return (
      <SessionDropZone
        id={`date:${row.groupId}:${row.dateGroup}`}
        groupId={row.groupId}
        style={style}
      >
        <SessionDateHeader dateGroup={row.dateGroup} label={row.label} />
      </SessionDropZone>
    );
  }

  const session = row.session;
  const channelKey = session.channel?.trim() || "";
  const channelLabel = channelKey
    ? getChannelLabel(channelKey, data.t)
    : undefined;
  const isEditing = data.editingSessionId === session.id;

  return (
    <SessionDropZone
      id={`session-target:${session.id}`}
      groupId={row.groupId}
      style={style}
    >
      <DraggableSession
        sessionId={session.id!}
        groupId={row.groupId}
        label={session.name || "New Chat"}
      >
        <SessionItem
          variant="sidebar"
          sessionId={session.id!}
          name={session.name || "New Chat"}
          channelKey={channelKey || undefined}
          channelLabel={channelLabel}
          chatStatus={session.status}
          generating={session.generating}
          archived={session.archived}
          pinned={session.pinned}
          source={session.source}
          groupId={row.groupId}
          groups={data.groups}
          active={
            session.id === data.currentSessionId ||
            (!!data.currentSessionId &&
              session.realId === data.currentSessionId)
          }
          disabled={false}
          editing={isEditing}
          editValue={isEditing ? data.editValue : undefined}
          onClick={data.handleSessionClick}
          onEdit={data.handleEditStart}
          onDelete={data.handleDelete}
          onArchive={data.handleArchiveToggle}
          onPin={data.handlePinToggle}
          onMove={data.handleMove}
          onEditChange={data.handleEditChange}
          onEditSubmit={data.handleEditSubmit}
          onEditCancel={data.handleEditCancel}
        />
      </DraggableSession>
    </SessionDropZone>
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
  const { message } = useAppMessage();
  const location = useLocation();
  const currentSessionId = getSessionIdFromPath(location.pathname) ?? undefined;

  const [searchQuery, setSearchQuery] = useState("");
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [isSessionDragging, setIsSessionDragging] = useState(false);
  /** Collapsed chat groups — persisted so remounts keep the user's state */
  const { collapsedGroups, toggleGroup, expandGroup } =
    useCollapsedChatGroups();
  const {
    groups: chatGroups,
    createGroup,
    renameGroup,
    pinGroup,
    deleteGroup,
    reorderGroups,
  } = useChatGroups(true);
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const visibleChatGroups = useMemo(
    () =>
      localizeSystemGroups(chatGroups, {
        default: t("chat.groups.uncategorized", "Uncategorized"),
        cron: t("chat.groups.cron", "Scheduled tasks"),
        subagents: t("chat.groups.subagents", "Subagents"),
      }),
    [chatGroups, t],
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
    handleArchiveToggle,
    handlePinToggle,
    handleEditChange,
    handleEditSubmit,
    handleEditCancel,
    refreshSessions,
  } = useSessionListData(storeSessions, setSessions, {
    active: true,
    currentSessionId,
    onSessionClick,
  });

  const handleMove = useCallback(
    async (sessionId: string, groupId: string, expandTarget = true) => {
      const session = storeSessions.find((item) => item.id === sessionId);
      const backendId = session ? getBackendId(session) : null;
      if (!backendId) return;
      try {
        await chatApi.updateChat(backendId, { group_id: groupId });
        await refreshSessions();
        if (expandTarget) expandGroup(groupId);
        const target = visibleChatGroups.find((group) => group.id === groupId);
        message.success(
          t("chat.groups.moveSuccess", "Moved to {{name}}", {
            name: target?.name ?? "",
          }),
        );
      } catch (error) {
        console.error("Failed to move conversation:", error);
        message.error(
          t("chat.groups.moveFailed", "Could not move the conversation"),
        );
      }
    },
    [
      expandGroup,
      message,
      refreshSessions,
      storeSessions,
      t,
      visibleChatGroups,
    ],
  );

  const handleDragMove = useCallback(
    (sessionId: string, groupId: string) => {
      void handleMove(sessionId, groupId, false);
    },
    [handleMove],
  );

  const handleCreateGroup = useCallback(async () => {
    const name = newGroupName.trim();
    if (!name) return;
    await createGroup(name);
    setCreatingGroup(false);
    setNewGroupName("");
  }, [createGroup, newGroupName]);

  const handleDeleteGroup = useCallback(
    (groupId: string) => {
      Modal.confirm({
        title: t("chat.groups.deleteTitle", "Delete this group?"),
        content: t(
          "chat.groups.deleteHint",
          "Conversations will return to their built-in group.",
        ),
        okButtonProps: { danger: true },
        onOk: async () => {
          await deleteGroup(groupId);
          await refreshSessions();
        },
      });
    },
    [deleteGroup, refreshSessions, t],
  );

  const handleMoveGroup = useCallback(
    async (groupId: string, offset: number) => {
      const source = chatGroups.find((group) => group.id === groupId);
      if (!source || source.kind === "cron" || source.kind === "subagents") {
        return;
      }
      const movable = chatGroups.filter(
        (group) =>
          group.kind !== "cron" &&
          group.kind !== "subagents" &&
          group.pinned === source.pinned,
      );
      const index = movable.findIndex((group) => group.id === groupId);
      const target = index + offset;
      if (index < 0 || target < 0 || target >= movable.length) return;
      const next = [...chatGroups];
      const sourceIndex = next.findIndex((group) => group.id === groupId);
      const targetIndex = next.findIndex(
        (group) => group.id === movable[target].id,
      );
      [next[sourceIndex], next[targetIndex]] = [
        next[targetIndex],
        next[sourceIndex],
      ];
      await reorderGroups(next.map((group) => group.id));
    },
    [chatGroups, reorderGroups],
  );

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
    () =>
      searchQuery.trim() ? null : groupChats(sortedSessions, visibleChatGroups),
    [sortedSessions, searchQuery, visibleChatGroups],
  );

  useRevealActiveChatGroup(currentSessionId, sortedSessions, expandGroup);

  /** Flatten groups into a single array of rows for virtual list */
  const flatRows = useMemo<FlatRow[]>(() => {
    if (searchQuery.trim()) {
      return filteredSessions.map((s) => ({
        kind: "session",
        session: s,
        groupId: resolveChatGroupId(s),
      }));
    }
    if (!groups) return [];
    const rows: FlatRow[] = [];
    for (const group of groups) {
      const collapsed =
        isSessionDragging || collapsedGroups.has(group.group.id);
      rows.push({
        kind: "groupHeader",
        group: group.group,
        count: group.sessions.length,
        collapsed,
      });
      if (!collapsed) {
        for (const dateGroup of groupChatsByDate(group.sessions)) {
          rows.push({
            kind: "dateHeader",
            groupId: group.group.id,
            dateGroup: dateGroup.key,
            label: t(`chat.group.${dateGroup.key}`),
          });
          for (const session of dateGroup.sessions) {
            rows.push({
              kind: "session",
              session,
              groupId: group.group.id,
            });
          }
        }
      }
    }
    return rows;
  }, [
    groups,
    collapsedGroups,
    isSessionDragging,
    searchQuery,
    filteredSessions,
    t,
  ]);

  /** Row height calculator for VariableSizeList */
  const getRowHeight = useCallback(
    (index: number) => {
      const row = flatRows[index];
      if (!row) return SESSION_ROW_HEIGHT;
      return row.kind === "groupHeader"
        ? GROUP_HEADER_HEIGHT
        : row.kind === "dateHeader"
        ? DATE_HEADER_HEIGHT
        : SESSION_ROW_HEIGHT;
    },
    [flatRows],
  );

  /** Height of the virtual list container */
  const [listHeight, setListHeight] = useState(0);
  const [visibleStartIndex, setVisibleStartIndex] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);
  const listRef = useRef<VariableSizeList>(null);

  useEffect(() => {
    if (isSessionDragging) listRef.current?.scrollTo(0);
  }, [isSessionDragging]);

  /** Reset virtual list cache when flatRows change */
  useEffect(() => {
    listRef.current?.resetAfterIndex(0);
  }, [flatRows]);

  // Bring the active conversation into view once its row is visible
  // (group expanded + list measured). Guarded by the last-scrolled id so
  // background polling doesn't keep yanking the scroll position.
  const lastScrolledSessionRef = useRef<string | null>(null);
  useEffect(() => {
    if (!currentSessionId) return;
    if (lastScrolledSessionRef.current === currentSessionId) return;
    const index = findSessionRowIndex(flatRows, currentSessionId);
    if (index < 0) return;
    lastScrolledSessionRef.current = currentSessionId;
    listRef.current?.scrollToItem(index, "smart");
  }, [currentSessionId, flatRows, listHeight]);

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
      handleArchiveToggle,
      handlePinToggle,
      handleMove,
      handleEditChange,
      handleEditSubmit,
      handleEditCancel,
      toggleGroup,
      groups: visibleChatGroups,
      renameGroup,
      pinGroup,
      deleteGroup: handleDeleteGroup,
      moveGroup: handleMoveGroup,
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
      handleArchiveToggle,
      handlePinToggle,
      handleMove,
      handleEditChange,
      handleEditSubmit,
      handleEditCancel,
      toggleGroup,
      visibleChatGroups,
      renameGroup,
      pinGroup,
      handleDeleteGroup,
      handleMoveGroup,
    ],
  );

  const stickyGroupRow = useMemo<GroupHeaderRow | null>(() => {
    if (searchQuery.trim() || isSessionDragging) return null;
    const index = findStickyGroupHeaderIndex(flatRows, visibleStartIndex);
    return index === null ? null : (flatRows[index] as GroupHeaderRow);
  }, [flatRows, isSessionDragging, searchQuery, visibleStartIndex]);

  return (
    <div className={styles.sessionList}>
      {/* Sticky header: new chat + history title + search */}
      <div className={styles.sessionListHeader}>
        {/* New Chat button */}
        <button className={styles.newChatBtn} onClick={handleNewChat}>
          <Plus size={14} />
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
            <ChevronDown size={12} />
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
            {creatingGroup ? (
              <Input
                autoFocus
                size="small"
                className={styles.groupInput}
                placeholder={t("chat.groups.namePlaceholder", "Group name")}
                value={newGroupName}
                onChange={(event) => setNewGroupName(event.target.value)}
                onPressEnter={() => void handleCreateGroup()}
                onBlur={() => {
                  if (!newGroupName.trim()) setCreatingGroup(false);
                }}
              />
            ) : (
              <button
                className={styles.createGroupBtn}
                onClick={() => setCreatingGroup(true)}
              >
                <FolderPlus size={13} />
                <span>{t("chat.groups.create", "New group")}</span>
              </button>
            )}
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
            <SessionGroupDndProvider
              onMove={handleDragMove}
              onDragStateChange={setIsSessionDragging}
            >
              {stickyGroupRow && (
                <div className={styles.stickyGroupHeader}>
                  <GroupHeaderContent
                    row={stickyGroupRow}
                    data={virtualListData}
                  />
                </div>
              )}
              <VariableSizeList
                ref={listRef}
                height={listHeight}
                width="100%"
                itemCount={flatRows.length}
                itemSize={getRowHeight}
                itemData={virtualListData}
                className={styles.list}
                overscanCount={10}
                onItemsRendered={({ visibleStartIndex: nextIndex }) =>
                  setVisibleStartIndex(nextIndex)
                }
              >
                {VirtualRow}
              </VariableSizeList>
            </SessionGroupDndProvider>
          )}
        </div>
      )}
    </div>
  );
}
