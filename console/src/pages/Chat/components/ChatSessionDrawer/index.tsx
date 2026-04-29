import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Drawer, Spin } from "antd";
import { FixedSizeList } from "react-window";
import { IconButton } from "@agentscope-ai/design";
import { SparkOperateRightLine } from "@agentscope-ai/icons";
import {
  useChatAnywhereSessionsState,
  useChatAnywhereSessions,
  type IAgentScopeRuntimeWebUISession,
} from "@agentscope-ai/chat";
import { useTranslation } from "react-i18next";
import type { ChatStatus } from "../../../../api/types/chat";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import ChatSessionItem from "../ChatSessionItem";
import { getChannelLabel } from "../../../Control/Channels/components";
import {
  ContextMenu,
  useContextMenu,
  type ContextMenuItem,
} from "../../../../components/ContextMenu";
import styles from "./index.module.less";

/** Fixed height of each session item in pixels (matches CSS min-height) */
const ITEM_HEIGHT = 77;

/** Sessions from QwenPaw backend include extra fields beyond the runtime UI type */
interface ExtendedChatSession extends IAgentScopeRuntimeWebUISession {
  realId?: string;
  sessionId?: string;
  userId?: string;
  channel?: string;
  createdAt?: string | null;
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
  const { sessions, currentSessionId, setCurrentSessionId, setSessions } =
    useChatAnywhereSessionsState();

  const { createSession } = useChatAnywhereSessions();

  /** Create a new session and close the drawer */
  const handleCreateSession = useCallback(async () => {
    await createSession();
    props.onClose();
  }, [createSession, props.onClose]);

  /** ID of the session currently being renamed */
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  /** Current value of the rename input */
  const [editValue, setEditValue] = useState("");

  /** Whether the session list is being fetched (default true because destroyOnClose re-mounts) */
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

  /** Sessions sorted by pinned first, then by createdAt descending */
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      const extA = a as ExtendedChatSession;
      const extB = b as ExtendedChatSession;

      if (extA.pinned && !extB.pinned) return -1;
      if (!extA.pinned && extB.pinned) return 1;

      const aTime = extA.createdAt;
      const bTime = extB.createdAt;
      if (!aTime && !bTime) return 0;
      if (!aTime) return 1;
      if (!bTime) return -1;
      return new Date(bTime).getTime() - new Date(aTime).getTime();
    });
  }, [sessions]);

  /** Re-fetch session list from the backend and sync to context state */
  const refreshSessions = useCallback(async () => {
    const list = await sessionApi.getSessionList();
    setSessions(list);
  }, [setSessions]);

  /** Open drawer → refresh session list */
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

    return () => {
      isCancelled = true;
    };
  }, [props.open, setSessions]);

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      setCurrentSessionId(sessionId);
    },
    [setCurrentSessionId],
  );

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

      if (currentSessionId === sessionId) {
        const next = sessions.filter((s) => s.id !== sessionId);
        setCurrentSessionId(next[0]?.id);
      }

      await refreshSessions();
    },
    [sessions, currentSessionId, setCurrentSessionId, refreshSessions],
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

  return (
    <Drawer
      open={props.open}
      onClose={props.onClose}
      destroyOnClose
      placement="right"
      width={360}
      closable={false}
      title={null}
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
      {/* Header bar */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.headerTitle}>{t("chat.allChats")}</span>
        </div>
        <div className={styles.headerRight}>
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
        ) : (
          <>
            {/* Background loading — only show when content overflows the container,
                so it's visible through unrendered gaps during fast scroll */}
            {sortedSessions.length * ITEM_HEIGHT > listHeight && (
              <div className={styles.virtualListBackground}>
                <Spin size="small" />
              </div>
            )}
            <FixedSizeList
              height={listHeight}
              width="100%"
              itemCount={sortedSessions.length}
              itemSize={ITEM_HEIGHT}
              overscanCount={20}
              className={styles.list}
            >
              {({ index, style }) => {
                const session = sortedSessions[index];
                const ext = session as ExtendedChatSession;
                const channelKey = ext.channel?.trim() || "";
                const channelLabel = channelKey
                  ? getChannelLabel(channelKey, t)
                  : undefined;
                return (
                  <div style={style}>
                    <ChatSessionItem
                      key={session.id}
                      sessionId={session.id!}
                      name={session.name || "New Chat"}
                      time={formatCreatedAt(ext.createdAt ?? null)}
                      channelKey={channelKey || undefined}
                      channelLabel={channelLabel}
                      chatStatus={ext.status}
                      generating={ext.generating}
                      pinned={ext.pinned}
                      active={session.id === currentSessionId}
                      editing={editingSessionId === session.id}
                      editValue={
                        editingSessionId === session.id ? editValue : undefined
                      }
                      onClick={handleSessionClick}
                      onEdit={handleEditStart}
                      onDelete={handleDelete}
                      onPin={handlePinToggle}
                      onEditChange={handleEditChange}
                      onEditSubmit={handleEditSubmit}
                      onEditCancel={handleEditCancel}
                      onContextMenu={handleItemContextMenu}
                    />
                  </div>
                );
              }}
            </FixedSizeList>
          </>
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
    </Drawer>
  );
};

export default ChatSessionDrawer;
