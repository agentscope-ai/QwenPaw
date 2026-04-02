import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Drawer } from "antd";
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
import styles from "./index.module.less";

/** Sessions from CoPaw backend include extra fields beyond the runtime UI type */
interface ExtendedChatSession extends IAgentScopeRuntimeWebUISession {
  realId?: string;
  sessionId?: string;
  userId?: string;
  channel?: string;
  createdAt?: string | null;
  meta?: Record<string, unknown>;
  status?: ChatStatus;
  generating?: boolean;
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

  /** Sessions sorted by createdAt descending, independent of context internal order */
  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      const aTime = (a as ExtendedChatSession).createdAt;
      const bTime = (b as ExtendedChatSession).createdAt;
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

  /** Open drawer → refresh session list (same deduped fetch as getSessionList). */
  useEffect(() => {
    if (!props.open) return;

    let isCancelled = false;

    const fetchSessions = async () => {
      try {
        const list = await sessionApi.getSessionList();
        if (!isCancelled) {
          setSessions(list);
        }
      } catch (error) {
        // It's good practice to log errors.
        console.error("Failed to refresh session list:", error);
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

  /** Submit rename: call updateChat with all original fields overriding only name, then refresh */
  const handleEditSubmit = useCallback(async () => {
    if (!editingSessionId) return;

    const session = sessions.find((s) => s.id === editingSessionId) as
      | ExtendedChatSession
      | undefined;
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
        created_at: session.createdAt ?? null,
        meta: session.meta,
        status: session.status,
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
      <div className={styles.listWrapper}>
        <div className={styles.topGradient} />
        <div className={styles.list}>
          {sortedSessions.map((session) => {
            const ext = session as ExtendedChatSession;
            const channelKey = ext.channel?.trim() || "";
            const channelLabel = channelKey
              ? getChannelLabel(channelKey, t)
              : undefined;
            return (
              <ChatSessionItem
                key={session.id}
                name={session.name || "New Chat"}
                time={formatCreatedAt(ext.createdAt ?? null)}
                channelKey={channelKey || undefined}
                channelLabel={channelLabel}
                chatStatus={ext.status}
                generating={ext.generating}
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
