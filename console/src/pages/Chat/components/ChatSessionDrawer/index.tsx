import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Drawer, Empty, Input, Modal, Spin, Tooltip } from "antd";
import { VariableSizeList, type ListChildComponentProps } from "react-window";
import { useTranslation } from "react-i18next";
import { useNavigate, useLocation } from "react-router-dom";
import { FolderPlus, PanelRightClose, Pin, PinOff } from "lucide-react";
import {
  useChatAnywhereSessionsState,
  type IAgentScopeRuntimeWebUISession,
} from "@agentscope-ai/chat";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import { useCollapsedChatGroups } from "../../../../hooks/useCollapsedChatGroups";
import { useRevealActiveChatGroup } from "../../../../hooks/useRevealActiveChatGroup";
import { useChatGroups } from "../../../../hooks/useChatGroups";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import SessionItem from "../../../../components/SessionItem";
import { formatSessionTime, pickSessionDisplayTime } from "./sessionTime";
import SessionGroupHeader from "../../../../components/SessionGroupHeader";
import SessionDateHeader from "../../../../components/SessionDateHeader";
import {
  DraggableSession,
  SessionDropZone,
  SessionGroupDndProvider,
} from "../../../../components/SessionGroupDnd";
import { getChannelLabel } from "../../../Control/Channels/components";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import { useMessageQueueStore } from "../../../../stores/messageQueueStore";
import {
  buildChatPath,
  getSessionIdFromPath,
} from "../../../../utils/sessionRoute";
import {
  syncSessionsGlobal,
  type ExtendedSession,
} from "../../../../stores/sessionListStore";
import { useAgentStore } from "../../../../stores/agentStore";
import { findSessionRowIndex } from "../../../../utils/sessionGrouping";
import {
  groupChats,
  groupChatsByDate,
  findStickyGroupHeaderIndex,
  localizeSystemGroups,
  resolveChatGroupId,
  type ChatDateGroup,
} from "../../../../utils/chatGroups";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { useSessionAttention } from "../../../../hooks/useSessionAttention";
import styles from "./index.module.less";
import type { ChatGroup, ChatStatus } from "../../../../api/types/chat";

/** Fixed height of each session item row */
const SESSION_ROW_HEIGHT = 77;
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

/** Data passed to each virtual row */
interface VirtualRowData {
  flatRows: FlatRow[];
  unseenSessionIds: ReadonlySet<string>;
  currentSessionId: string | undefined;
  switchingSessionId: string | null;
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

/** Virtual list row renderer — handles both group headers and session items */
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
          variant="drawer"
          sessionId={session.id!}
          name={session.name || "New Chat"}
          time={formatCreatedAtCached(pickSessionDisplayTime(session))}
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
            session.id === data.switchingSessionId ||
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

/** Sessions from QwenPaw backend include extra fields beyond the runtime UI type */
interface ExtendedChatSession extends IAgentScopeRuntimeWebUISession {
  realId?: string;
  sessionId?: string;
  userId?: string;
  channel?: string;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastFinishedAt?: string | null;
  meta?: Record<string, unknown>;
  status?: ChatStatus;
  generating?: boolean;
  pinned?: boolean;
  archivedAt?: string | null;
  archived?: boolean;
  source?: "chat" | "cron" | "subagent";
  groupId?: string | null;
  parentSessionId?: string | null;
  rootSessionId?: string | null;
}

interface ChatSessionDrawerProps {
  /** Whether the drawer is visible */
  open: boolean;
  /** Callback to close the drawer */
  onClose: () => void;
  /** Whether the drawer is pinned (stays open) */
  pinned?: boolean;
  /** Callback to toggle the pinned state */
  onPinChange?: (pinned: boolean) => void;
  /**
   * When true, render as an inline panel instead of an antd Drawer.
   * The parent is responsible for layout (width, positioning, etc.).
   */
  embedded?: boolean;
}

/** Format an ISO 8601 timestamp to YYYY-MM-DD HH:mm:ss (sessionTime module) */

/** Simple cache for formatSessionTime to avoid re-parsing the same timestamp */
const formatCache = new Map<string, string>();
const FORMAT_CACHE_MAX = 200;

const formatCreatedAtCached = (raw: string | null | undefined): string => {
  if (!raw) return "";
  const cached = formatCache.get(raw);
  if (cached !== undefined) return cached;
  const result = formatSessionTime(raw);
  if (formatCache.size >= FORMAT_CACHE_MAX) {
    // Evict oldest entry
    const firstKey = formatCache.keys().next().value;
    if (firstKey !== undefined) formatCache.delete(firstKey);
  }
  formatCache.set(raw, result);
  return result;
};

/** Resolve the real backend UUID from an extended session (id may be a local timestamp) */
const getBackendId = (session: ExtendedChatSession): string | null => {
  if (session.realId) return session.realId;
  const id = session.id;
  if (!/^\d+$/.test(id)) return id;
  return null;
};

const ChatSessionDrawer: React.FC<ChatSessionDrawerProps> = (props) => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const navigate = useNavigate();
  const location = useLocation();
  const sdkState = useChatAnywhereSessionsState();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const createNewSession = useCreateNewSession();

  // In embedded mode, maintain a local session list fetched directly from the
  // API so we don't depend on the SDK context tree (which lives inside
  // AgentScopeRuntimeWebUI and may not be accessible from outside).
  const [localSessions, setLocalSessions] = useState<
    IAgentScopeRuntimeWebUISession[]
  >([]);

  // Always use the component's own localSessions state.  In non-embedded
  // mode (mobile full mode) this component is rendered outside the
  // AgentScopeRuntimeWebUI context tree, where sdkState.sessions would be
  // the default empty context value and sdkState.setSessions a no-op.
  const sessions = localSessions;
  const { currentSessionId: sdkCurrentSessionId } = sdkState;
  // Prefer URL-derived chatId for active-state matching in ALL modes —
  // the SDK context may not be accessible from outside the provider.
  const urlCurrentSessionId =
    getSessionIdFromPath(location.pathname) ?? undefined;
  const currentSessionId = urlCurrentSessionId || sdkCurrentSessionId;
  const setSessions = setLocalSessions;
  const { embedded, pinned, onClose } = props;

  /** Create a new session; close the drawer only when not pinned */
  const handleCreateSession = useCallback(async () => {
    if (sessionApi.isSessionSwitching) {
      sessionApi.finishSessionSwitch();
    }
    if (embedded) {
      window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
    } else {
      await createNewSession();
      if (!pinned) {
        onClose();
      }
    }
  }, [createNewSession, onClose, pinned, embedded]);

  /** ID of the session currently being renamed */
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  /** Current value of the rename input */
  const [editValue, setEditValue] = useState("");

  /** Whether the session list is being fetched (default true because destroyOnHidden re-mounts) */
  const [listLoading, setListLoading] = useState(true);

  /** Cache last polled sessions to skip no-op state updates */
  const lastPolledSessionsRef = useRef<IAgentScopeRuntimeWebUISession[]>([]);

  const { collapsedGroups, toggleGroup, expandGroup } =
    useCollapsedChatGroups();
  const {
    groups: chatGroups,
    createGroup,
    renameGroup,
    pinGroup,
    deleteGroup,
    reorderGroups,
  } = useChatGroups(props.open);
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [isSessionDragging, setIsSessionDragging] = useState(false);
  const visibleChatGroups = useMemo(
    () =>
      localizeSystemGroups(chatGroups, {
        default: t("chat.groups.uncategorized", "Uncategorized"),
        cron: t("chat.groups.cron", "Scheduled tasks"),
        subagents: t("chat.groups.subagents", "Subagents"),
      }),
    [chatGroups, t],
  );

  /** Immediate search input value (bound to Input, updates on every keystroke) */
  const [searchInput, setSearchInput] = useState("");
  /** Debounced search query used for actual filtering (300ms delay) */
  const [searchQuery, setSearchQuery] = useState("");

  /** Debounce search input to avoid excessive re-renders during fast typing */
  useEffect(() => {
    const handle = setTimeout(() => setSearchQuery(searchInput), 300);
    return () => clearTimeout(handle);
  }, [searchInput]);

  /** Sessions sorted by updatedAt/createdAt descending.
   *  Filter out local temporary sessions (created by clicking "New Chat" but
   *  not yet persisted to backend). These sessions have local timestamp IDs
   *  (matching /^\d+-[a-z0-9]+$/) and no realId field. They should only appear
   *  in the list after the first message is sent and the backend creates them.
   */
  const resolvedSessions = useMemo(() => {
    return sessions.filter((session) => {
      const ext = session as ExtendedChatSession;
      const isLocalId = /^\d+-[a-z0-9]+$/.test(session.id);
      const hasRealId = !!ext.realId;
      return !isLocalId || hasRealId;
    });
  }, [sessions]);

  const sortedSessions = useMemo(() => {
    return [...resolvedSessions]
      .filter((s) => !(s as ExtendedChatSession).archived)
      .sort((a, b) => {
        const extA = a as ExtendedChatSession;
        const extB = b as ExtendedChatSession;

        const aTime = pickSessionDisplayTime(extA) ?? "";
        const bTime = pickSessionDisplayTime(extB) ?? "";
        if (!aTime && !bTime) return 0;
        if (!aTime) return 1;
        if (!bTime) return -1;
        return bTime < aTime ? -1 : bTime > aTime ? 1 : 0;
      });
  }, [resolvedSessions]);

  const unseenSessionIds = useSessionAttention(
    selectedAgent,
    sortedSessions as ExtendedChatSession[],
    currentSessionId,
  );

  /** Re-fetch session list from the backend and sync to context state */
  const refreshSessions = useCallback(async () => {
    const owner = sessionApi.getActiveOwner();
    const list = await sessionApi.getSessionList();
    // Never publish a list that finished loading under a previous agent.
    if (!sessionApi.isActiveOwner(owner)) return;
    setSessions(list);
  }, [setSessions]);

  /** Open drawer → refresh session list and start polling */
  useEffect(() => {
    if (!props.open) return;

    let isCancelled = false;
    const owner = sessionApi.getActiveOwner();

    // The drawer owns a local list outside the SDK context. Clear the
    // previous agent's entries before loading the newly selected agent.
    lastPolledSessionsRef.current = [];
    setSessions([]);

    const fetchSessions = async () => {
      setListLoading(true);
      try {
        const list = await sessionApi.getSessionList();
        if (!isCancelled && sessionApi.isActiveOwner(owner)) {
          // sessionApi already returns the previous array reference when the
          // list hasn't changed, so a reference check is enough to skip no-op
          // state updates and avoid a full re-render cascade.
          if (list !== lastPolledSessionsRef.current) {
            lastPolledSessionsRef.current = list;
            setSessions(list);
          }
        }
      } catch (error) {
        console.error("Failed to refresh session list:", error);
      } finally {
        if (!isCancelled) {
          setListLoading(false);
        }
      }
    };

    void fetchSessions();

    const timer = setInterval(async () => {
      // Pause polling during session switch to avoid bandwidth contention
      if (sessionApi.isSessionSwitching) return;
      try {
        const list = await sessionApi.getSessionList();
        if (!isCancelled && sessionApi.isActiveOwner(owner)) {
          // sessionApi already returns the previous array reference when the
          // list hasn't changed, so a reference check is enough to skip no-op
          // state updates and avoid a full re-render cascade.
          if (list !== lastPolledSessionsRef.current) {
            lastPolledSessionsRef.current = list;
            setSessions(list);
          }
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);

    return () => {
      isCancelled = true;
      clearInterval(timer);
    };
  }, [props.open, selectedAgent, setSessions]);

  /** Whether a session switch is in progress (issue #4557) */
  const [switchingSessionId, setSwitchingSessionId] = useState<string | null>(
    null,
  );

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      if (sessionId === currentSessionId) {
        return;
      }

      // Both embedded and non-embedded modes use the same switching logic
      // as simple mode's SidebarSessionList: just navigate to the session
      // URL. ChatSessionInitializer's useEffect will pick up the URL change
      // and call setCurrentSessionId(matching.id) to notify the SDK.
      // This avoids the preload / isSessionSwitching complexity that caused
      // the "flash to new chat" issue.
      setSwitchingSessionId(sessionId);
      const effectiveId = sessionApi.getEffectiveSessionId(sessionId);
      const targetPath = buildChatPath(effectiveId);
      navigate(targetPath);
    },
    [currentSessionId, navigate],
  );

  // Listen for embedded switch completion so we can clear switchingSessionId.
  useEffect(() => {
    const onDone = () => {
      setSwitchingSessionId(null);
    };
    window.addEventListener("qwenpaw:sidebar-switch-done", onDone);
    return () =>
      window.removeEventListener("qwenpaw:sidebar-switch-done", onDone);
  }, []);

  // In embedded mode, clear switchingSessionId when the URL changes
  // (signals that the session switch initiated via DOM event has completed).
  useEffect(() => {
    if (props.embedded && switchingSessionId) {
      setSwitchingSessionId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  /** Delete a session: call deleteChat API then refresh the list */
  const handleDelete = useCallback(
    async (sessionId: string) => {
      const owner = sessionApi.getActiveOwner();
      const session = sessions.find((s) => s.id === sessionId) as
        | ExtendedChatSession
        | undefined;
      const backendId = session ? getBackendId(session) : null;

      if (backendId) {
        await chatApi.deleteChat(backendId);
      }

      // Per-session cleanup is safe regardless of the active agent: it is
      // keyed to the deleted conversation only.
      localStorage.removeItem(`approval_level-${sessionId}`);

      // Clear the message queue for the deleted session so stale items don't
      // linger in storage or get sent after deletion. The queue may be keyed
      // by the local id or the resolved backend id, so clear both.
      const mq = useMessageQueueStore.getState();
      mq.clear(sessionId);
      if (backendId && backendId !== sessionId) mq.clear(backendId);

      // Everything below mutates the CURRENT view (callbacks, shared list,
      // navigation). A delete that finished after an agent switch must not
      // touch the new agent's state.
      if (!sessionApi.isActiveOwner(owner)) return;
      sessionApi.onSessionRemoved?.(backendId ?? sessionId);

      // Fetch the updated session list after deletion
      const freshList =
        (await sessionApi.getSessionList()) as ExtendedChatSession[];
      if (!sessionApi.isActiveOwner(owner)) return;
      setSessions(freshList);
      syncSessionsGlobal(freshList as unknown as ExtendedSession[]);

      // Post-deletion check: if the URL's chatId no longer exists in the
      // refreshed list, the deleted session was the one being viewed.
      // This approach avoids all ID-format mismatch issues (timestamp vs UUID,
      // realId vs id, multiple backend UUIDs for the same session).
      const urlChatId = getSessionIdFromPath(location.pathname);
      if (urlChatId) {
        const stillExists = freshList.some(
          (s) =>
            s.id === urlChatId ||
            (s as ExtendedChatSession).realId === urlChatId,
        );
        if (!stillExists) {
          window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
        }
      }
    },
    [sessions, setSessions, location.pathname],
  );

  /** Enter rename mode for a session */
  const handleEditStart = useCallback(
    (sessionId: string, currentName: string) => {
      setEditingSessionId(sessionId);
      setEditValue(currentName);
    },
    [],
  );

  /** Update rename input value */
  const handleEditChange = useCallback((value: string) => {
    setEditValue(value);
  }, []);

  /** Submit rename */
  const handleEditSubmit = useCallback(async () => {
    if (!editingSessionId) return;
    const owner = sessionApi.getActiveOwner();

    const session = sessions.find((s) => s.id === editingSessionId) as
      | ExtendedChatSession
      | undefined;
    const backendId = session ? getBackendId(session) : null;
    const newName = editValue.trim();

    if (backendId && newName && session) {
      await chatApi.updateChat(backendId, {
        name: newName,
      });
    }

    setEditingSessionId(null);
    setEditValue("");
    if (!sessionApi.isActiveOwner(owner)) return;
    await refreshSessions();
  }, [editingSessionId, editValue, sessions, refreshSessions]);

  /** Cancel rename mode */
  const handleEditCancel = useCallback(() => {
    setEditingSessionId(null);
    setEditValue("");
  }, []);

  /** Toggle archive status for a session */
  const handleArchiveToggle = useCallback(
    async (sessionId: string) => {
      const owner = sessionApi.getActiveOwner();
      const session = sessions.find((s) => s.id === sessionId) as
        | ExtendedChatSession
        | undefined;
      const backendId = session ? getBackendId(session) : null;
      if (!backendId) return;
      const wasArchived = !!session?.archived;
      try {
        if (wasArchived) {
          await chatApi.unarchiveChat(backendId);
        } else {
          await chatApi.archiveChat(backendId);
        }
        if (!sessionApi.isActiveOwner(owner)) return;
        message.success(
          wasArchived
            ? t("sessions.archive.unarchiveSuccess", "Chat unarchived")
            : t("sessions.archive.successHint"),
        );
        await refreshSessions();

        if (!wasArchived) {
          const urlChatId = getSessionIdFromPath(location.pathname);
          if (
            urlChatId &&
            (sessionId === urlChatId || backendId === urlChatId)
          ) {
            window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
          }
        }
      } catch (err) {
        console.error("Failed to toggle archive status:", err);
        message.error(
          t("sessions.archive.failed", "Failed to update archive status"),
        );
      }
    },
    [sessions, refreshSessions, location.pathname, message, t],
  );

  const handlePinToggle = useCallback(
    async (sessionId: string, pinned: boolean) => {
      const owner = sessionApi.getActiveOwner();
      const session = sessions.find((item) => item.id === sessionId) as
        | ExtendedChatSession
        | undefined;
      const backendId = session ? getBackendId(session) : null;
      if (!backendId) return;
      try {
        await chatApi.updateChat(backendId, { pinned });
        if (!sessionApi.isActiveOwner(owner)) return;
        await refreshSessions();
      } catch (error) {
        console.error("Failed to update conversation pin:", error);
        message.error(
          t("chat.contextMenu.pinFailed", "Could not update pinned state"),
        );
      }
    },
    [message, refreshSessions, sessions, t],
  );

  const handleMove = useCallback(
    async (sessionId: string, groupId: string, expandTarget = true) => {
      const session = sessions.find((item) => item.id === sessionId) as
        | ExtendedChatSession
        | undefined;
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
    [expandGroup, message, refreshSessions, sessions, t, visibleChatGroups],
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

  /** Filter sessions by search query */
  const filteredSessions = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return sortedSessions;
    return sortedSessions.filter((session) =>
      ((session as ExtendedChatSession).name || "New Chat")
        .toLowerCase()
        .includes(query),
    );
  }, [sortedSessions, searchQuery]);

  const groups = useMemo(
    () =>
      searchQuery.trim()
        ? null
        : groupChats(
            sortedSessions as ExtendedChatSession[],
            visibleChatGroups,
          ),
    [sortedSessions, searchQuery, visibleChatGroups],
  );

  useRevealActiveChatGroup(
    currentSessionId,
    sortedSessions as ExtendedChatSession[],
    expandGroup,
  );

  /** Flatten groups into a single array of rows for virtual list */
  const flatRows = useMemo<FlatRow[]>(() => {
    if (searchQuery.trim()) {
      return filteredSessions.map((s) => ({
        kind: "session",
        session: s as ExtendedChatSession,
        groupId: resolveChatGroupId(s as ExtendedChatSession),
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

  /** Height of the virtual list container, measured via ResizeObserver */
  const [listHeight, setListHeight] = useState(0);
  const [visibleStartIndex, setVisibleStartIndex] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);
  const listRef = useRef<VariableSizeList>(null);

  useEffect(() => {
    if (isSessionDragging) listRef.current?.scrollTo(0);
  }, [isSessionDragging]);

  /** Reset virtual list cache when flatRows change (group collapse/expand) */
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
      unseenSessionIds,
      currentSessionId,
      switchingSessionId,
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
      unseenSessionIds,
      currentSessionId,
      switchingSessionId,
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

  const panelContent = (
    <>
      {/* Header bar */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.headerTitle}>{t("chat.allChats")}</span>
        </div>
        <div className={styles.headerRight}>
          {!props.embedded && (
            <Tooltip
              title={
                props.pinned
                  ? t("chat.unpinDrawer", "Unpin")
                  : t("chat.pinDrawer", "Pin")
              }
              mouseEnterDelay={0.5}
            >
              <button
                type="button"
                className={`${styles.headerIconButton} ${
                  props.pinned ? styles.pinActive : ""
                }`}
                aria-label={
                  props.pinned
                    ? t("chat.unpinDrawer", "Unpin")
                    : t("chat.pinDrawer", "Pin")
                }
                onClick={() => props.onPinChange?.(!props.pinned)}
              >
                {props.pinned ? <PinOff size={16} /> : <Pin size={16} />}
              </button>
            </Tooltip>
          )}
          <button
            type="button"
            className={styles.headerIconButton}
            aria-label={t("common.close", "Close")}
            onClick={props.onClose}
          >
            <PanelRightClose size={16} />
          </button>
        </div>
      </div>

      {/* Create new chat button */}
      <div className={styles.createSection}>
        <div className={styles.createButton} onClick={handleCreateSession}>
          {t("chat.createNewChat")}
        </div>
      </div>

      {/* Search bar */}
      <div className={styles.searchContainer}>
        <Input
          size="small"
          allowClear
          placeholder={t("chat.sessionPanel.searchConversations", "Search…")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
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
            type="button"
            className={styles.createGroupButton}
            onClick={() => setCreatingGroup(true)}
          >
            <FolderPlus size={14} />
            <span>{t("chat.groups.create", "New group")}</span>
          </button>
        )}
      </div>

      {/* Session list */}
      <div className={styles.listWrapper} ref={listWrapperRef}>
        <div className={styles.topGradient} />
        {listLoading ? (
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              padding: 40,
            }}
          >
            <Spin />
          </div>
        ) : sortedSessions.length === 0 ? (
          <Empty
            description={t("chat.history.empty", "No chat history")}
            style={{ marginTop: 80 }}
          />
        ) : flatRows.length === 0 ? (
          <div className={styles.emptyState}>
            {t("chat.sessionPanel.noResults", "No results")}
          </div>
        ) : (
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
        <div className={styles.bottomGradient} />
      </div>
    </>
  );

  // Mobile viewport detection so the drawer width matches the search panel.
  const isMobile = useIsMobile();

  // Embedded mode: render as an inline panel (no Drawer wrapper)
  if (props.embedded) {
    if (!props.open) return null;
    return <div className={styles.embeddedPanel}>{panelContent}</div>;
  }

  // Drawer mode (legacy)
  return (
    <Drawer
      open={props.open}
      onClose={props.pinned ? undefined : props.onClose}
      destroyOnHidden={!props.pinned}
      placement="right"
      width={isMobile ? "calc(100vw - 56px)" : 330}
      closable={false}
      title={null}
      mask={!props.pinned}
      styles={{
        header: { display: "none" },
        body: {
          padding: 0,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          overflow: "hidden",
        },
        mask: { background: "transparent" },
      }}
      className={styles.drawer}
    >
      {panelContent}
    </Drawer>
  );
};

export default ChatSessionDrawer;
