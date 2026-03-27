import React, { useCallback, useState } from "react";
import { Drawer } from "antd";
import { IconButton } from "@agentscope-ai/design";
import { SparkOperateRightLine } from "@agentscope-ai/icons";
import {
  useChatAnywhereSessionsState,
  useChatAnywhereSessions,
} from "@agentscope-ai/chat";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import ChatSessionItem from "../ChatSessionItem";
import styles from "./index.module.less";

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

/** Resolve the real backend UUID from an ExtendedSession record (id may be a local timestamp) */
const getBackendId = (session: Record<string, unknown>): string | null => {
  if (session.realId) return session.realId as string;
  const id = session.id as string;
  if (!/^\d+$/.test(id)) return id;
  return null;
};

const ChatSessionDrawer: React.FC<ChatSessionDrawerProps> = (props) => {
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

  /** Re-fetch session list from the backend and sync to context state */
  const refreshSessions = useCallback(async () => {
    const list = await sessionApi.getSessionList();
    setSessions(list);
  }, [setSessions]);

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      setCurrentSessionId(sessionId);
    },
    [setCurrentSessionId],
  );

  /** Delete a session: call deleteChat API then refresh the list */
  const handleDelete = useCallback(
    async (sessionId: string) => {
      const session = sessions.find((s) => s.id === sessionId) as Record<
        string,
        unknown
      >;
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

  /** Submit rename: call updateChat with all original fields overriding only name, then refresh */
  const handleEditSubmit = useCallback(async () => {
    if (!editingSessionId) return;

    const session = sessions.find((s) => s.id === editingSessionId) as Record<
      string,
      unknown
    >;
    const backendId = session ? getBackendId(session) : null;
    const newName = editValue.trim();

    if (backendId && newName && session) {
      // Reconstruct full ChatSpec from ExtendedSession, replacing only the name
      await chatApi.updateChat(backendId, {
        id: backendId,
        name: newName,
        session_id: session.sessionId as string,
        user_id: session.userId as string,
        channel: session.channel as string,
        created_at: (session.createdAt as string | null) ?? null,
        meta: session.meta as Record<string, unknown> | undefined,
        status: session.status as "idle" | "running" | undefined,
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

  return (
    <Drawer
      open={props.open}
      onClose={props.onClose}
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
          <span className={styles.headerTitle}>History</span>
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
          Create New Chat
        </div>
      </div>

      {/* Session list */}
      <div className={styles.listWrapper}>
        <div className={styles.topGradient} />
        <div className={styles.list}>
          {sessions.map((session) => {
            const raw = session as Record<string, unknown>;
            return (
              <ChatSessionItem
                key={session.id}
                name={session.name || "New Chat"}
                time={formatCreatedAt(raw.createdAt as string | null)}
                active={session.id === currentSessionId}
                editing={editingSessionId === session.id}
                editValue={
                  editingSessionId === session.id ? editValue : undefined
                }
                onClick={() => handleSessionClick(session.id!)}
                onEdit={() =>
                  handleEditStart(session.id!, session.name || "New Chat")
                }
                onDelete={() => handleDelete(session.id!)}
                onEditChange={handleEditChange}
                onEditSubmit={handleEditSubmit}
                onEditCancel={handleEditCancel}
              />
            );
          })}
        </div>
        <div className={styles.bottomGradient} />
      </div>
    </Drawer>
  );
};

export default ChatSessionDrawer;
