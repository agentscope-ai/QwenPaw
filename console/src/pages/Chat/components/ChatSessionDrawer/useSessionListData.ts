import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { IAgentScopeRuntimeWebUISession } from "@agentscope-ai/chat";
import type { ChatStatus } from "../../../../api/types/chat";
import { chatApi } from "../../../../api/modules/chat";
import sessionApi from "../../sessionApi";
import {
  ContextMenu,
  useContextMenu,
  type ContextMenuItem,
} from "../../../../components/ContextMenu";
import { getChannelLabel } from "../../../Control/Channels/components";
import { syncSessionsGlobal } from "../../../../stores/sessionListStore";

export { ContextMenu, useContextMenu, type ContextMenuItem, getChannelLabel };

/** Sessions from QwenPaw backend include extra fields beyond the runtime UI type */
export interface ExtendedChatSession extends IAgentScopeRuntimeWebUISession {
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

/** Resolve the real backend UUID from an extended session (id may be a local timestamp) */
export const getBackendId = (session: ExtendedChatSession): string | null => {
  if (session.realId) return session.realId;
  const id = session.id;
  if (!/^\d+$/.test(id)) return id;
  return null;
};

/** Format an ISO 8601 timestamp to YYYY-MM-DD HH:mm:ss */
export const formatCreatedAt = (raw: string | null | undefined): string => {
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

interface UseSessionListDataOptions {
  /** Whether to start fetching (works like `open` in the drawer) */
  active: boolean;
  /** Current session id — used to determine active item and block no-op clicks */
  currentSessionId: string | undefined;
  /** Called when user clicks a session; the hook itself does NOT navigate */
  onSessionClick: (sessionId: string) => void;
  /** Called when the session list changes so the parent can sync (optional) */
  onSessionsChange?: (sessions: ExtendedChatSession[]) => void;
}

export interface SessionListData {
  sortedSessions: ExtendedChatSession[];
  loading: boolean;
  /** ID of session whose switch is in flight (null = none) */
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
  /** Shared context-menu state */
  contextMenu: ReturnType<typeof useContextMenu>;
  contextMenuItems: ContextMenuItem[];
  refreshSessions: () => Promise<void>;
}

/**
 * Shared session-list logic extracted from ChatSessionDrawer.
 * Both ChatSessionDrawer and SidebarSessionList use this hook.
 *
 * The `onSessionClick` callback is injected by the caller so that:
 * - ChatSessionDrawer can call setCurrentSessionId directly (inside context).
 * - SidebarSessionList can dispatch a DOM event (outside context).
 */
export function useSessionListData(
  sessions: ExtendedChatSession[],
  setSessions: (s: ExtendedChatSession[]) => void,
  opts: UseSessionListDataOptions,
): SessionListData {
  const { t } = useTranslation();
  const { active, currentSessionId, onSessionClick } = opts;

  const [loading, setLoading] = useState(true);
  const [switchingSessionId, setSwitchingSessionId] = useState<string | null>(
    null,
  );
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const sharedContextMenu = useContextMenu();
  const [contextMenuSessionId, setContextMenuSessionId] = useState<
    string | null
  >(null);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await sessionApi.getSessionList();
      const extended = list as ExtendedChatSession[];
      setSessions(extended);
      syncSessionsGlobal(extended);
    } catch (err) {
      console.error("useSessionListData: failed to fetch sessions", err);
    }
  }, [setSessions]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const fetchSessions = async () => {
      setLoading(true);
      try {
        const list = await sessionApi.getSessionList();
        if (!cancelled) {
          const extended = list as ExtendedChatSession[];
          setSessions(extended);
          syncSessionsGlobal(extended);
        }
      } catch (err) {
        console.error("useSessionListData: failed to fetch sessions", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void fetchSessions();

    const timer = setInterval(async () => {
      try {
        const list = await sessionApi.getSessionList();
        if (!cancelled) {
          const extended = list as ExtendedChatSession[];
          setSessions(extended);
          syncSessionsGlobal(extended);
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [active, setSessions]);

  const sortedSessions = useMemo(() => {
    return [...sessions].sort((a, b) => {
      if (a.pinned && !b.pinned) return -1;
      if (!a.pinned && b.pinned) return 1;
      const aTime = a.updatedAt ?? a.createdAt;
      const bTime = b.updatedAt ?? b.createdAt;
      if (!aTime && !bTime) return 0;
      if (!aTime) return 1;
      if (!bTime) return -1;
      return new Date(bTime).getTime() - new Date(aTime).getTime();
    });
  }, [sessions]);

  const handleSessionClick = useCallback(
    (sessionId: string) => {
      if (sessionApi.isSessionSwitching) return;
      if (sessionId === currentSessionId) return;
      setSwitchingSessionId(sessionId);
      onSessionClick(sessionId);
    },
    [currentSessionId, onSessionClick],
  );

  // Clear switchingSessionId once the URL / currentSessionId has settled
  useEffect(() => {
    setSwitchingSessionId(null);
  }, [currentSessionId]);

  const handleDelete = useCallback(
    async (sessionId: string) => {
      const session = sessions.find((s) => s.id === sessionId);
      const backendId = session ? getBackendId(session) : null;
      if (backendId) await chatApi.deleteChat(backendId);

      // Fetch fresh session list after deletion
      const freshList =
        (await sessionApi.getSessionList()) as ExtendedChatSession[];
      setSessions(freshList);
      syncSessionsGlobal(freshList);

      // Post-deletion check: if the currently displayed session no longer
      // exists in the refreshed list, navigate to a new blank chat.
      // This avoids all ID-format mismatch issues between URL chatId,
      // session.id, and session.realId.
      if (currentSessionId) {
        const stillExists = freshList.some(
          (s) =>
            s.id === currentSessionId ||
            (s as ExtendedChatSession).realId === currentSessionId,
        );
        if (!stillExists) {
          window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
        }
      }
    },
    [sessions, currentSessionId, setSessions],
  );

  const handleEditStart = useCallback(
    (sessionId: string, currentName: string) => {
      setEditingSessionId(sessionId);
      setEditValue(currentName);
    },
    [],
  );

  const handleEditChange = useCallback((value: string) => {
    setEditValue(value);
  }, []);

  const handleEditSubmit = useCallback(async () => {
    if (!editingSessionId) return;
    const session = sessions.find((s) => s.id === editingSessionId);
    const backendId = session ? getBackendId(session) : null;
    const newName = editValue.trim();
    if (backendId && newName) {
      await chatApi.updateChat(backendId, { name: newName });
    }
    setEditingSessionId(null);
    setEditValue("");
    await refreshSessions();
  }, [editingSessionId, editValue, sessions, refreshSessions]);

  const handleEditCancel = useCallback(() => {
    setEditingSessionId(null);
    setEditValue("");
  }, []);

  const handlePinToggle = useCallback(
    async (sessionId: string) => {
      const session = sessions.find((s) => s.id === sessionId);
      const backendId = session ? getBackendId(session) : null;
      if (backendId && session) {
        try {
          await chatApi.updateChat(backendId, { pinned: !session.pinned });
          await refreshSessions();
        } catch (err) {
          console.error("Failed to toggle pin status:", err);
        }
      }
    },
    [sessions, refreshSessions],
  );

  const handleItemContextMenu = useCallback(
    (sessionId: string, event: React.MouseEvent) => {
      setContextMenuSessionId(sessionId);
      sharedContextMenu.show(event);
    },
    [sharedContextMenu],
  );

  const contextMenuItems: ContextMenuItem[] = useMemo(() => {
    if (!contextMenuSessionId) return [];
    const session = sessions.find((s) => s.id === contextMenuSessionId);
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

  return {
    sortedSessions,
    loading,
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
    contextMenu: sharedContextMenu,
    contextMenuItems,
    refreshSessions,
  };
}
