import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  buildSessionPath,
  getSessionIdFromPath,
} from "../../../../utils/sessionRoute";
import { Drawer, Empty, Spin, Tooltip } from "antd";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import { FixedSizeList, type ListChildComponentProps } from "react-window";
import { IconButton } from "@agentscope-ai/design";
import {
  SparkOperateRightLine,
  SparkLockLine,
  SparkLockFill,
} from "@agentscope-ai/icons";
import {
  useChatAnywhereSessionsState,
  type IAgentScopeRuntimeWebUISession,
} from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import type { ChatStatus } from "../../../../api/types/chat";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import { useCreateNewSession } from "../../hooks/useCreateNewSession";
import { useCodingMode } from "../../../../stores/codingModeStore";
import { useAgentStore } from "../../../../stores/agentStore";
import ChatSessionItem from "../ChatSessionItem";
import { getChannelLabel } from "../../../Control/Channels/components";
import {
  ContextMenu,
  useContextMenu,
  type ContextMenuItem,
} from "../../../../components/ContextMenu";
import {
  syncSessionsGlobal,
  type ExtendedSession,
} from "../../../../stores/sessionListStore";
import styles from "./index.module.less";

/** Fixed height of each session item in pixels (matches CSS min-height) */
const ITEM_HEIGHT = 77;

/** Data passed to each row via FixedSizeList's itemData prop */
interface SessionRowData {
  sortedSessionsRef: React.MutableRefObject<ExtendedChatSession[]>;
  currentSessionId: string | undefined;
  /** When non-null, the target session shows active state immediately */
  switchingSessionId: string | null;
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
  handleItemContextMenu: (sessionId: string, event: React.MouseEvent) => void;
}

/** Memoized row renderer — only re-renders when its specific props change */
const SessionRow = React.memo(function SessionRow({
  index,
  style,
  data,
}: ListChildComponentProps<SessionRowData>) {
  const session = data.sortedSessionsRef.current[index];
  if (!session) return null;
  const channelKey = session.channel?.trim() || "";
  const channelLabel = channelKey
    ? getChannelLabel(channelKey, data.t)
    : undefined;
  const isEditing = data.editingSessionId === session.id;

  return (
    <div style={style}>
      <ChatSessionItem
        sessionId={session.id!}
        name={session.name || "New Chat"}
        time={formatCreatedAt(session.createdAt ?? null)}
        channelKey={channelKey || undefined}
        channelLabel={channelLabel}
        chatStatus={session.status}
        generating={session.generating}
        pinned={session.pinned}
        active={
          session.id === data.currentSessionId ||
          session.id === data.switchingSessionId ||
          (!!data.currentSessionId &&
            (session as ExtendedChatSession).realId === data.currentSessionId)
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
        onContextMenu={data.handleItemContextMenu}
      />
    </div>
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
  meta?: Record<string, unknown>;
  status?: ChatStatus;
  generating?: boolean;
  pinned?: boolean;
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

/** Format an ISO 8601 timestamp to YYYY-MM-DD HH:mm:ss */
const formatCreatedAt = (raw: string | null | undefined): string => {
  if (!raw) return "";
  const date = new Date(raw);
  if (isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`;
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
  const navigate = useNavigate();
  const location = useLocation();
  const sdkState = useChatAnywhereSessionsState();
  const { codingMode } = useCodingMode();
  const { selectedAgent, setLastChatId } = useAgentStore();

  const createNewSession = useCreateNewSession();

  // In embedded mode, maintain a local session list fetched directly from the
  // API so we don't depend on the SDK context tree (which lives inside
  // AgentScopeRuntimeWebUI and may not be accessible from outside).
  const [localSessions, setLocalSessions] = useState<
    IAgentScopeRuntimeWebUISession[]
  >([]);

  const sessions = props.embedded ? localSessions : sdkState.sessions;
  const { currentSessionId: sdkCurrentSessionId, setCurrentSessionId } =
    sdkState;
  // In embedded mode, prefer URL-derived chatId for active-state matching
  // because the SDK context may not be accessible from outside the provider.
  const urlCurrentSessionId = props.embedded
    ? getSessionIdFromPath(location.pathname) ?? undefined
    : undefined;
  const currentSessionId = urlCurrentSessionId || sdkCurrentSessionId;
  const setSessions = props.embedded ? setLocalSessions : sdkState.setSessions;
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

  /** Height of the virtual list container, measured via ResizeObserver */
  const [listHeight, setListHeight] = useState(0);
  const observerRef = useRef<ResizeObserver | null>(null);

  /** Callback ref: attach a ResizeObserver whenever the wrapper DOM node appears */
  const listWrapperRef = useCallback((node: HTMLDivElement | null) => {
    // Cleanup previous observer
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }

    if (!node) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const height = entry.contentRect.height;
        if (height > 0) {
          setListHeight(height);
        }
      }
    });

    observer.observe(node);
    observerRef.current = observer;

    // Measure immediately in case layout is already stable
    const initialHeight = node.clientHeight;
    if (initialHeight > 0) {
      setListHeight(initialHeight);
    }
  }, []);

  /** Shared context menu — only one instance instead of one per item */
  const sharedContextMenu = useContextMenu();
  const [contextMenuSessionId, setContextMenuSessionId] = useState<
    string | null
  >(null);

  /** Sessions sorted by pinned first, then by updatedAt/createdAt descending */
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      const extA = a as ExtendedChatSession;
      const extB = b as ExtendedChatSession;

      if (extA.pinned && !extB.pinned) return -1;
      if (!extA.pinned && extB.pinned) return 1;

      // ISO 8601 strings are lexicographically sortable — avoid new Date()
      const aTime = extA.updatedAt ?? extA.createdAt ?? "";
      const bTime = extB.updatedAt ?? extB.createdAt ?? "";
      if (!aTime && !bTime) return 0;
      if (!aTime) return 1;
      if (!bTime) return -1;
      return bTime < aTime ? -1 : bTime > aTime ? 1 : 0;
    });
  }, [sessions]);

  /** Re-fetch session list from the backend and sync to context state */
  const refreshSessions = useCallback(async () => {
    const list = await sessionApi.getSessionList();
    setSessions(list);
  }, [setSessions]);

  /** Open drawer → refresh session list and start polling */
  useEffect(() => {
    if (!props.open) return;

    let isCancelled = false;

    const fetchSessions = async () => {
      setListLoading(true);
      try {
        const list = await sessionApi.getSessionList();
        if (!isCancelled) {
          setSessions(list);
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
        if (!isCancelled) {
          setSessions(list);
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);

    return () => {
      isCancelled = true;
      clearInterval(timer);
    };
  }, [props.open, setSessions]);

  /** Whether a session switch is in progress (issue #4557) */
  const [switchingSessionId, setSwitchingSessionId] = useState<string | null>(
    null,
  );

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      if (sessionId === currentSessionId) {
        return;
      }

      if (props.embedded) {
        setSwitchingSessionId(sessionId);
        window.dispatchEvent(
          new CustomEvent("qwenpaw:sidebar-select-session", {
            detail: { sessionId },
          }),
        );
        return;
      }

      // Start a new cancellable switch (aborts any in-flight switch)
      const controller = sessionApi.startNewSwitch();
      setSwitchingSessionId(sessionId);

      sessionApi
        .preloadSession(sessionId, controller.signal)
        .then(({ realId }) => {
          if (controller.signal.aborted) return;
          const effectiveId = sessionApi.getEffectiveSessionId(
            sessionId,
            realId,
          );
          // Issue #4987: In coding mode, skip URL navigation to /chat/<id>.
          // The redirect effect in ChatPage would immediately navigate back
          // to /coding before session data loads, causing the switch to fail.
          if (!codingMode) {
            const targetUrl = buildSessionPath("chat", effectiveId);
            navigate(targetUrl, { replace: true });
          }
          sessionApi.trackNavigatedSession(
            effectiveId,
            setLastChatId,
            selectedAgent,
          );
          setCurrentSessionId(sessionId);
        })
        .catch((err) => {
          if (err?.name === "AbortError") return;
          // On non-abort error, still try to switch normally.
          setCurrentSessionId(sessionId);
        })
        .finally(() => {
          // Only clean up if this switch was NOT superseded by a newer one
          if (!controller.signal.aborted) {
            sessionApi.finishSessionSwitch();
            setSwitchingSessionId(null);
          }
        });
    },
    [
      currentSessionId,
      setCurrentSessionId,
      navigate,
      codingMode,
      selectedAgent,
      setLastChatId,
      props.embedded,
    ],
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
      const session = sessions.find((s) => s.id === sessionId) as
        | ExtendedChatSession
        | undefined;
      const backendId = session ? getBackendId(session) : null;

      if (backendId) {
        await chatApi.deleteChat(backendId);
      }

      // Fetch the updated session list after deletion
      const freshList =
        (await sessionApi.getSessionList()) as ExtendedChatSession[];
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
    await refreshSessions();
  }, [editingSessionId, editValue, sessions, refreshSessions]);

  /** Cancel rename mode */
  const handleEditCancel = useCallback(() => {
    setEditingSessionId(null);
    setEditValue("");
  }, []);

  /** Toggle pin status for a session */
  const handlePinToggle = useCallback(
    async (sessionId: string) => {
      const session = sessions.find((s) => s.id === sessionId) as
        | ExtendedChatSession
        | undefined;
      const backendId = session ? getBackendId(session) : null;

      if (backendId && session) {
        try {
          const newPinnedState = !session.pinned;
          await chatApi.updateChat(backendId, {
            pinned: newPinnedState,
          });
          await refreshSessions();
        } catch (error) {
          console.error("Failed to toggle pin status:", error);
        }
      }
    },
    [sessions, refreshSessions],
  );

  /** Show shared context menu for a specific session */
  const handleItemContextMenu = useCallback(
    (sessionId: string, event: React.MouseEvent) => {
      setContextMenuSessionId(sessionId);
      sharedContextMenu.show(event);
    },
    [sharedContextMenu],
  );

  /** Build context menu items for the currently right-clicked session */
  const contextMenuItems: ContextMenuItem[] = useMemo(() => {
    if (!contextMenuSessionId) return [];
    const session = sessions.find((s) => s.id === contextMenuSessionId) as
      | ExtendedChatSession
      | undefined;
    return [
      {
        key: "open",
        label: t("chat.contextMenu.open", "Open"),
        onClick: () => handleSessionClick(contextMenuSessionId),
      },
      {
        key: "rename",
        label: t("chat.contextMenu.rename", "Rename"),
        onClick: () =>
          handleEditStart(contextMenuSessionId, session?.name || "New Chat"),
      },
      {
        key: "pin",
        label: session?.pinned
          ? t("chat.contextMenu.unpin", "Unpin")
          : t("chat.contextMenu.pin", "Pin"),
        onClick: () => handlePinToggle(contextMenuSessionId),
      },
      { key: "divider-1", label: "", divider: true },
      {
        key: "delete",
        label: t("chat.contextMenu.delete", "Delete"),
        danger: true,
        onClick: () => handleDelete(contextMenuSessionId),
      },
    ];
  }, [
    contextMenuSessionId,
    sessions,
    t,
    handleSessionClick,
    handleEditStart,
    handlePinToggle,
    handleDelete,
  ]);

  /** Stable data object for FixedSizeList — avoids re-creating row renderer on every render */
  const sortedSessionsRef = useRef(sortedSessions);
  sortedSessionsRef.current = sortedSessions;

  const itemData = useMemo<SessionRowData>(
    () => ({
      sortedSessionsRef,
      currentSessionId,
      switchingSessionId,
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
      handleItemContextMenu,
    }),
    [
      currentSessionId,
      switchingSessionId,
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
      handleItemContextMenu,
    ],
  );

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
              <IconButton
                bordered={false}
                icon={props.pinned ? <SparkLockFill /> : <SparkLockLine />}
                className={props.pinned ? styles.pinActive : undefined}
                onClick={() => props.onPinChange?.(!props.pinned)}
              />
            </Tooltip>
          )}
          <IconButton
            bordered={false}
            icon={<SparkOperateRightLine />}
            onClick={props.onClose}
          />
        </div>
      </div>

      {/* Create new chat button */}
      <div className={styles.createSection}>
        <div className={styles.createButton} onClick={handleCreateSession}>
          {t("chat.createNewChat")}
        </div>
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
        ) : (
          <FixedSizeList
            height={listHeight}
            width="100%"
            itemCount={sortedSessions.length}
            itemSize={ITEM_HEIGHT}
            overscanCount={20}
            itemData={itemData}
            className={styles.list}
          >
            {SessionRow}
          </FixedSizeList>
        )}
        <div className={styles.bottomGradient} />
      </div>

      {/* Shared context menu — single instance for all session items */}
      <ContextMenu
        visible={sharedContextMenu.visible}
        x={sharedContextMenu.x}
        y={sharedContextMenu.y}
        items={contextMenuItems}
        onClose={sharedContextMenu.hide}
      />
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
