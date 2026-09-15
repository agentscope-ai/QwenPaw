import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Dropdown, Input, Modal, Spin, Tooltip } from "antd";
import type { InputRef } from "antd";
import { VariableSizeList, type ListChildComponentProps } from "react-window";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import {
  CalendarDays,
  ChevronDown,
  Ellipsis,
  FolderPlus,
  FolderTree,
  Layers,
  List,
  Search,
} from "lucide-react";
import { SparkNewChatLine } from "@agentscope-ai/icons";
import { getChannelLabel } from "../pages/Control/Channels/components";
import {
  getBackendId,
  useSessionListData,
  type ExtendedChatSession,
} from "./useSidebarSessionListData";
import { getSessionIdFromPath } from "../utils/sessionRoute";
import {
  useSessionListStore,
  syncSessionsGlobal,
  type ExtendedSession,
} from "../stores/sessionListStore";
import { findSessionRowIndex } from "../utils/sessionGrouping";
import {
  getSessionGroupModePreference,
  setSessionGroupModePreference,
  SESSION_GROUP_MODE_CHANGE_EVENT,
  type SessionGroupMode,
} from "../utils/sessionGroupModePreference";
import {
  groupChats,
  groupChatsByDate,
  findStickyGroupHeaderIndex,
  localizeSystemGroups,
  resolveChatGroupId,
  type ChatDateGroup,
} from "../utils/chatGroups";
import { useCollapsedChatGroups } from "../hooks/useCollapsedChatGroups";
import { useCompactDensity } from "../hooks/useCompactDensity";
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
import { useSessionAttention } from "../hooks/useSessionAttention";
import { useAgentStore } from "../stores/agentStore";
import styles from "./sidebarSessionList.module.less";

/** Fixed height of each session item row */
const SESSION_ROW_HEIGHT = 42;
/** Fixed height of each group header row */
const GROUP_HEADER_HEIGHT = 42;
const DATE_HEADER_HEIGHT = 24;
const LOAD_MORE_ROW_HEIGHT = 44;
const GROUP_PAGE_SIZE = 10;

/**
 * Compact row metrics for short viewports (see useCompactDensity).
 * Each value must match the `@media (max-height: 850px)` rules in the
 * session list stylesheets so the virtualized allocation and the
 * rendered rows stay in lockstep.
 */
const SESSION_ROW_HEIGHT_COMPACT = 30;
const GROUP_HEADER_HEIGHT_COMPACT = 32;
const DATE_HEADER_HEIGHT_COMPACT = 20;
const LOAD_MORE_ROW_HEIGHT_COMPACT = 36;

/** A flattened row rendered by the virtualized session list. */
type FlatRow =
  | {
      kind: "groupHeader";
      group: ChatGroup;
      count: number;
      collapsed: boolean;
    }
  | {
      kind: "dateHeader";
      dateGroup: ChatDateGroup;
      label: string;
    }
  | {
      kind: "loadMore";
      sectionId: string;
      remaining: number;
    }
  | { kind: "session"; session: ExtendedChatSession; groupId: string };

/**
 * A paginated section of the session list. Sections are chat groups in
 * source mode, date buckets in date mode, and one flat list in none
 * mode; `visibleSessionCounts` pages each section independently.
 */
interface ListSection {
  id: string;
  header: FlatRow | null;
  sessions: ExtendedChatSession[];
  /** Group id stamped on session rows; null resolves per session. */
  groupId: string | null;
  collapsed: boolean;
}

/** Section id of the single flat section used by "none" mode. */
const FLAT_SECTION_ID = "flat:all";

// ── Component ─────────────────────────────────────────────────────────────

/** Data passed to each virtual row */
interface VirtualRowData {
  flatRows: FlatRow[];
  unseenSessionIds: ReadonlySet<string>;
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
  loadMoreGroup: (sectionId: string) => void;
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
    // Date headers only exist in date mode, where they carry no group
    // semantics, so they are not drag-and-drop targets.
    return (
      <div style={style}>
        <SessionDateHeader dateGroup={row.dateGroup} label={row.label} />
      </div>
    );
  }

  if (row.kind === "loadMore") {
    const label = data.t(
      "chat.groups.loadMore",
      "Load more · {{count}} remaining",
      {
        count: row.remaining,
      },
    );
    return (
      <div className={styles.loadMoreRow} style={style}>
        <button
          type="button"
          className={styles.loadMoreButton}
          aria-label={label}
          onClick={() => data.loadMoreGroup(row.sectionId)}
        >
          <span>{label}</span>
          <ChevronDown size={13} />
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
          sessionId={session.id!}
          name={session.name || "New Chat"}
          channelKey={channelKey || undefined}
          channelLabel={channelLabel}
          chatStatus={session.status}
          generating={session.generating}
          unseenResult={data.unseenSessionIds.has(session.id)}
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
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const location = useLocation();
  const currentSessionId = getSessionIdFromPath(location.pathname) ?? undefined;

  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(false);
  const [isSessionDragging, setIsSessionDragging] = useState(false);
  /** Sectioning mode — persisted and synced across mounted lists. */
  const [groupMode, setGroupMode] = useState<SessionGroupMode>(
    getSessionGroupModePreference,
  );
  /** Compact row metrics on short viewports (small laptops). */
  const compact = useCompactDensity();

  useEffect(() => {
    const syncGroupMode = () => {
      setGroupMode(getSessionGroupModePreference());
    };

    window.addEventListener(SESSION_GROUP_MODE_CHANGE_EVENT, syncGroupMode);
    return () => {
      window.removeEventListener(
        SESSION_GROUP_MODE_CHANGE_EVENT,
        syncGroupMode,
      );
    };
  }, []);

  const handleGroupModeChange = useCallback((mode: SessionGroupMode) => {
    setGroupMode(mode);
    setSessionGroupModePreference(mode);
  }, []);
  /** Collapsed chat groups — persisted so remounts keep the user's state */
  const {
    collapsedGroups,
    toggleGroup,
    expandGroup,
    initializeCollapsedGroups,
  } = useCollapsedChatGroups();
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
  const [visibleSessionCounts, setVisibleSessionCounts] = useState<
    Record<string, number>
  >({});
  const searchInputRef = useRef<InputRef>(null);
  const groupInputRef = useRef<InputRef>(null);
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

  const unseenSessionIds = useSessionAttention(
    selectedAgent,
    sortedSessions,
    currentSessionId,
  );

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

  const handleOpenSearch = useCallback(() => {
    setHistoryCollapsed(false);
    setCreatingGroup(false);
    setSearchOpen(true);
    window.setTimeout(() => searchInputRef.current?.focus(), 0);
  }, []);

  const handleOpenCreateGroup = useCallback(() => {
    setHistoryCollapsed(false);
    setSearchOpen(false);
    setSearchQuery("");
    setCreatingGroup(true);
    window.setTimeout(() => groupInputRef.current?.focus(), 0);
  }, []);

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

  /**
   * Sections drive the virtual list: one per chat group (source mode),
   * one per date bucket (date mode), or a single flat section (none
   * mode). Pagination and active-session reveal operate on section ids.
   */
  const sections = useMemo<ListSection[]>(() => {
    if (searchQuery.trim()) return [];
    if (groupMode === "date") {
      return groupChatsByDate(sortedSessions).map((dateGroup) => ({
        id: `date:${dateGroup.key}`,
        header: {
          kind: "dateHeader" as const,
          dateGroup: dateGroup.key,
          label: t(`chat.group.${dateGroup.key}`),
        },
        sessions: dateGroup.sessions,
        groupId: null,
        collapsed: false,
      }));
    }
    if (groupMode === "none") {
      const ordered = groupChatsByDate(sortedSessions).flatMap(
        (dateGroup) => dateGroup.sessions,
      );
      if (ordered.length === 0) return [];
      return [
        {
          id: FLAT_SECTION_ID,
          header: null,
          sessions: ordered,
          groupId: null,
          collapsed: false,
        },
      ];
    }
    if (!groups) return [];
    return groups.map(({ group, sessions }) => {
      const collapsed = isSessionDragging || collapsedGroups.has(group.id);
      return {
        id: group.id,
        header: {
          kind: "groupHeader" as const,
          group,
          count: sessions.length,
          collapsed,
        },
        // Keep the pinned-first, recency-second order the nested date
        // headers used to provide, without rendering the date rows.
        sessions: groupChatsByDate(sessions).flatMap(
          (dateGroup) => dateGroup.sessions,
        ),
        groupId: group.id,
        collapsed,
      };
    });
  }, [
    collapsedGroups,
    groupMode,
    groups,
    isSessionDragging,
    searchQuery,
    sortedSessions,
    t,
  ]);

  const activeSessionPage = useMemo(() => {
    if (!currentSessionId) return null;
    for (const section of sections) {
      const sessionIndex = section.sessions.findIndex(
        (session) =>
          session.id === currentSessionId ||
          session.realId === currentSessionId,
      );
      if (sessionIndex < 0) continue;
      return {
        sectionId: section.id,
        requiredCount:
          Math.floor(sessionIndex / GROUP_PAGE_SIZE + 1) * GROUP_PAGE_SIZE,
      };
    }
    return null;
  }, [currentSessionId, sections]);

  /**
   * Group that owns the active session, resolved through `groupChats`
   * so sessions in deleted groups fall back to their source bucket.
   * Mode-independent: it keeps source-mode collapse defaults stable
   * while the list is displayed in date or none mode.
   */
  const activeGroupId = useMemo(() => {
    if (!currentSessionId || !groups) return null;
    const activeGroup = groups.find(({ sessions }) =>
      sessions.some(
        (session) =>
          session.id === currentSessionId ||
          session.realId === currentSessionId,
      ),
    );
    return activeGroup?.group.id ?? null;
  }, [currentSessionId, groups]);

  const defaultCollapsedGroupIds = useMemo(() => {
    if (!groups) return new Set<string>();

    const expandableGroupIds = new Set(
      groups
        .filter(
          ({ group }) => group.kind !== "cron" && group.kind !== "subagents",
        )
        .map(({ group }) => group.id),
    );
    const recentGroupIds = new Set<string>();
    for (const session of sortedSessions) {
      const groupId = resolveChatGroupId(session);
      if (!expandableGroupIds.has(groupId)) continue;
      recentGroupIds.add(groupId);
      if (recentGroupIds.size === 2) break;
    }
    if (activeGroupId) {
      recentGroupIds.add(activeGroupId);
    }

    // If there are no conversations yet, keep the first two user groups
    // discoverable while leaving fixed system groups collapsed.
    if (recentGroupIds.size === 0) {
      groups
        .filter(
          ({ group }) => group.kind !== "cron" && group.kind !== "subagents",
        )
        .slice(0, 2)
        .forEach(({ group }) => recentGroupIds.add(group.id));
    }

    return new Set(
      groups
        .filter(
          ({ group }) =>
            !recentGroupIds.has(group.id) &&
            (group.kind === "cron" ||
              group.kind === "subagents" ||
              !group.pinned),
        )
        .map(({ group }) => group.id),
    );
  }, [activeGroupId, groups, sortedSessions]);

  useEffect(() => {
    if (loading) return;
    initializeCollapsedGroups(defaultCollapsedGroupIds);
  }, [defaultCollapsedGroupIds, initializeCollapsedGroups, loading]);

  useEffect(() => {
    setVisibleSessionCounts({});
  }, [selectedAgent]);

  const loadMoreGroup = useCallback((sectionId: string) => {
    setVisibleSessionCounts((previous) => ({
      ...previous,
      [sectionId]: (previous[sectionId] ?? GROUP_PAGE_SIZE) + GROUP_PAGE_SIZE,
    }));
  }, []);

  useEffect(() => {
    if (!activeSessionPage) return;
    setVisibleSessionCounts((previous) => {
      const currentCount =
        previous[activeSessionPage.sectionId] ?? GROUP_PAGE_SIZE;
      if (currentCount >= activeSessionPage.requiredCount) return previous;
      return {
        ...previous,
        [activeSessionPage.sectionId]: activeSessionPage.requiredCount,
      };
    });
  }, [activeSessionPage]);

  useRevealActiveChatGroup(currentSessionId, sortedSessions, expandGroup);

  /** Flatten sections into a single array of rows for virtual list */
  const flatRows = useMemo<FlatRow[]>(() => {
    if (searchQuery.trim()) {
      return filteredSessions.map((s) => ({
        kind: "session",
        session: s,
        groupId: resolveChatGroupId(s),
      }));
    }
    const rows: FlatRow[] = [];
    for (const section of sections) {
      if (section.header) rows.push(section.header);
      if (section.collapsed) continue;
      const visibleCount = Math.min(
        visibleSessionCounts[section.id] ?? GROUP_PAGE_SIZE,
        section.sessions.length,
      );
      for (const session of section.sessions.slice(0, visibleCount)) {
        rows.push({
          kind: "session",
          session,
          groupId: section.groupId ?? resolveChatGroupId(session),
        });
      }
      if (visibleCount < section.sessions.length) {
        rows.push({
          kind: "loadMore",
          sectionId: section.id,
          remaining: section.sessions.length - visibleCount,
        });
      }
    }
    return rows;
  }, [sections, searchQuery, filteredSessions, visibleSessionCounts]);

  /** Row height calculator for VariableSizeList */
  const getRowHeight = useCallback(
    (index: number) => {
      const row = flatRows[index];
      if (!row) {
        return compact ? SESSION_ROW_HEIGHT_COMPACT : SESSION_ROW_HEIGHT;
      }
      if (row.kind === "groupHeader") {
        return compact ? GROUP_HEADER_HEIGHT_COMPACT : GROUP_HEADER_HEIGHT;
      }
      if (row.kind === "dateHeader") {
        return compact ? DATE_HEADER_HEIGHT_COMPACT : DATE_HEADER_HEIGHT;
      }
      if (row.kind === "loadMore") {
        return compact ? LOAD_MORE_ROW_HEIGHT_COMPACT : LOAD_MORE_ROW_HEIGHT;
      }
      return compact ? SESSION_ROW_HEIGHT_COMPACT : SESSION_ROW_HEIGHT;
    },
    [compact, flatRows],
  );

  /** Height of the virtual list container */
  const [listHeight, setListHeight] = useState(0);
  const [visibleStartIndex, setVisibleStartIndex] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);
  const listRef = useRef<VariableSizeList>(null);

  useEffect(() => {
    if (isSessionDragging) listRef.current?.scrollTo(0);
  }, [isSessionDragging]);

  /** Reset virtual list cache when flatRows or row density change */
  useEffect(() => {
    listRef.current?.resetAfterIndex(0);
  }, [compact, flatRows]);

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
      unseenSessionIds,
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
      loadMoreGroup,
      toggleGroup,
      groups: visibleChatGroups,
      renameGroup,
      pinGroup,
      deleteGroup: handleDeleteGroup,
      moveGroup: handleMoveGroup,
    }),
    [
      flatRows,
      unseenSessionIds,
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
      loadMoreGroup,
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
      {/* Sticky history header and compact actions. */}
      <div className={styles.sessionListHeader}>
        <div className={styles.historyHeaderRow}>
          <button
            className={styles.historyHeader}
            type="button"
            aria-expanded={!historyCollapsed}
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
          <div className={styles.historyActions}>
            <Tooltip title={t("chat.newTask", "New task")}>
              <button
                type="button"
                className={styles.historyAction}
                aria-label={t("chat.newTask", "New task")}
                onClick={handleNewChat}
              >
                <SparkNewChatLine size={18} />
              </button>
            </Tooltip>
            <Dropdown
              trigger={["click"]}
              placement="bottomRight"
              menu={{
                selectable: true,
                selectedKeys: [`group-mode-${groupMode}`],
                items: [
                  {
                    key: "search",
                    icon: <Search size={15} />,
                    label: t(
                      "chat.sessionPanel.searchConversations",
                      "Search conversations",
                    ),
                    onClick: handleOpenSearch,
                  },
                  {
                    key: "create-group",
                    icon: <FolderPlus size={15} />,
                    label: t("chat.groups.create", "New group"),
                    onClick: handleOpenCreateGroup,
                  },
                  { type: "divider" as const },
                  {
                    key: "group-mode",
                    icon: <Layers size={15} />,
                    label: t("chat.sessionPanel.groupBy", "Group by"),
                    children: [
                      {
                        key: "group-mode-date",
                        icon: <CalendarDays size={15} />,
                        label: t("chat.sessionPanel.groupByDate", "By date"),
                        onClick: () => handleGroupModeChange("date"),
                      },
                      {
                        key: "group-mode-source",
                        icon: <FolderTree size={15} />,
                        label: t(
                          "chat.sessionPanel.groupBySource",
                          "By source",
                        ),
                        onClick: () => handleGroupModeChange("source"),
                      },
                      {
                        key: "group-mode-none",
                        icon: <List size={15} />,
                        label: t(
                          "chat.sessionPanel.groupByNone",
                          "No grouping",
                        ),
                        onClick: () => handleGroupModeChange("none"),
                      },
                    ],
                  },
                ],
              }}
            >
              <button
                type="button"
                className={styles.historyAction}
                aria-label={t("sidebar.more", "More")}
              >
                <Ellipsis size={16} />
              </button>
            </Dropdown>
          </div>
        </div>

        {!historyCollapsed && (searchOpen || creatingGroup) && (
          <div className={styles.searchContainer}>
            {searchOpen && (
              <Input
                ref={searchInputRef}
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
            )}
            {creatingGroup && (
              <Input
                ref={groupInputRef}
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
