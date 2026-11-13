import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { chatApi } from "../../../api/modules/chat";
import type { ChatUpdateRequest } from "../../../api/types";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useAgentStore } from "../../../stores/agentStore";
import type { Session } from "./components/constants";

type SessionsState = {
  agentId: string;
  sessions: Session[];
  loading: boolean;
  error: Error | null;
};

export function useSessions() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();
  const selectedAgentRef = useRef(selectedAgent);
  const messageRef = useRef(message);
  const tRef = useRef(t);
  const requestIdRef = useRef(0);
  const stateRef = useRef<SessionsState>({
    agentId: selectedAgent,
    sessions: [],
    loading: true,
    error: null,
  });
  const [state, setState] = useState<SessionsState>(stateRef.current);
  const [activeTab, setActiveTab] = useState<"active" | "archived">("active");

  selectedAgentRef.current = selectedAgent;
  messageRef.current = message;
  tRef.current = t;

  const commitState = useCallback((next: SessionsState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const fetchSessions = useCallback(
    async (agentId?: string) => {
      const requestAgentId = agentId ?? selectedAgentRef.current;
      const requestId = ++requestIdRef.current;
      const isCurrent = () =>
        requestIdRef.current === requestId &&
        selectedAgentRef.current === requestAgentId;

      if (!isCurrent()) return;
      commitState({
        agentId: requestAgentId,
        sessions: [],
        loading: true,
        error: null,
      });

      try {
        const data = await chatApi.listChats({ agentId: requestAgentId });
        if (isCurrent()) {
          commitState({
            agentId: requestAgentId,
            sessions: (data ?? []) as Session[],
            loading: true,
            error: null,
          });
        }
      } catch (error) {
        if (isCurrent()) {
          console.error("Failed to load sessions:", error);
          commitState({
            agentId: requestAgentId,
            sessions: [],
            loading: true,
            error:
              error instanceof Error
                ? error
                : new Error("Failed to load sessions"),
          });
        }
      } finally {
        if (isCurrent()) {
          commitState({ ...stateRef.current, loading: false });
        }
      }
    },
    [commitState],
  );

  useEffect(() => {
    void fetchSessions(selectedAgent);
  }, [fetchSessions, selectedAgent]);

  const canMutate = useCallback(
    (ownerAgentId: string) =>
      selectedAgentRef.current === ownerAgentId &&
      stateRef.current.agentId === ownerAgentId &&
      !stateRef.current.loading,
    [],
  );

  const rejectStaleMutation = useCallback(
    (ownerAgentId: string) => {
      if (canMutate(ownerAgentId)) return false;
      void fetchSessions(selectedAgentRef.current);
      return true;
    },
    [canMutate, fetchSessions],
  );

  const updateSession = useCallback(
    async (
      sessionId: string,
      values: ChatUpdateRequest,
      ownerAgentId = selectedAgentRef.current,
    ) => {
      if (rejectStaleMutation(ownerAgentId)) return false;
      try {
        const result = await api.updateSession(sessionId, values, ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        commitState({
          ...stateRef.current,
          sessions: stateRef.current.sessions.map((session) =>
            session.id === sessionId ? result : session,
          ),
        });
        messageRef.current.success(tRef.current("sessions.saveSuccess"));
        return true;
      } catch (error) {
        if (!canMutate(ownerAgentId)) return false;
        console.error("Failed to save session:", error);
        messageRef.current.error(tRef.current("sessions.saveFailed"));
        return false;
      }
    },
    [canMutate, commitState, rejectStaleMutation],
  );

  const deleteSession = useCallback(
    async (sessionId: string, ownerAgentId = selectedAgentRef.current) => {
      if (rejectStaleMutation(ownerAgentId)) return false;
      try {
        await api.deleteSession(sessionId, ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        commitState({
          ...stateRef.current,
          sessions: stateRef.current.sessions.filter(
            (session) => session.id !== sessionId,
          ),
        });
        messageRef.current.success(tRef.current("sessions.deleteSuccess"));
        return true;
      } catch (error) {
        if (!canMutate(ownerAgentId)) return false;
        console.error("Failed to delete session:", error);
        messageRef.current.error(tRef.current("sessions.deleteFailed"));
        return false;
      }
    },
    [canMutate, commitState, rejectStaleMutation],
  );

  const batchDeleteSessions = useCallback(
    async (sessionIds: string[], ownerAgentId = selectedAgentRef.current) => {
      if (rejectStaleMutation(ownerAgentId)) return false;
      try {
        await api.batchDeleteSessions(sessionIds, ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        commitState({
          ...stateRef.current,
          sessions: stateRef.current.sessions.filter(
            (session) => !sessionIds.includes(session.id),
          ),
        });
        messageRef.current.success(
          tRef.current("sessions.batchDeleteSuccess", {
            count: sessionIds.length,
          }),
        );
        return true;
      } catch (error) {
        if (!canMutate(ownerAgentId)) return false;
        console.error("Failed to batch delete sessions:", error);
        messageRef.current.error(tRef.current("sessions.batchDeleteFailed"));
        return false;
      }
    },
    [canMutate, commitState, rejectStaleMutation],
  );

  const archiveSession = useCallback(
    async (sessionId: string, ownerAgentId = selectedAgentRef.current) => {
      if (rejectStaleMutation(ownerAgentId)) return false;
      try {
        const updated = await chatApi.archiveChat(sessionId, ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        commitState({
          ...stateRef.current,
          sessions: stateRef.current.sessions.map((session) =>
            session.id === sessionId ? (updated as Session) : session,
          ),
        });
        messageRef.current.success(
          tRef.current("sessions.archive.successHint"),
        );
        return true;
      } catch (error) {
        if (!canMutate(ownerAgentId)) return false;
        console.error("Failed to archive session:", error);
        messageRef.current.error(
          tRef.current("sessions.archive.failed", "Failed to archive"),
        );
        return false;
      }
    },
    [canMutate, commitState, rejectStaleMutation],
  );

  const unarchiveSession = useCallback(
    async (sessionId: string, ownerAgentId = selectedAgentRef.current) => {
      if (rejectStaleMutation(ownerAgentId)) return false;
      try {
        const updated = await chatApi.unarchiveChat(sessionId, ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        commitState({
          ...stateRef.current,
          sessions: stateRef.current.sessions.map((session) =>
            session.id === sessionId ? (updated as Session) : session,
          ),
        });
        messageRef.current.success(
          tRef.current("sessions.archive.unarchiveSuccess", "Chat unarchived"),
        );
        return true;
      } catch (error) {
        if (!canMutate(ownerAgentId)) return false;
        console.error("Failed to unarchive session:", error);
        messageRef.current.error(
          tRef.current(
            "sessions.archive.unarchiveFailed",
            "Failed to unarchive",
          ),
        );
        return false;
      }
    },
    [canMutate, commitState, rejectStaleMutation],
  );

  const batchArchiveSessions = useCallback(
    async (sessionIds: string[], ownerAgentId = selectedAgentRef.current) => {
      if (rejectStaleMutation(ownerAgentId)) return false;
      try {
        await chatApi.batchArchiveChats(sessionIds, ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        await fetchSessions(ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        messageRef.current.success(
          tRef.current("sessions.archive.batchSuccess", {
            count: sessionIds.length,
            defaultValue: "{{count}} chats archived",
          }),
        );
        return true;
      } catch (error) {
        if (!canMutate(ownerAgentId)) return false;
        console.error("Failed to batch archive sessions:", error);
        messageRef.current.error(
          tRef.current(
            "sessions.archive.batchFailed",
            "Failed to batch archive",
          ),
        );
        return false;
      }
    },
    [canMutate, fetchSessions, rejectStaleMutation],
  );

  const batchUnarchiveSessions = useCallback(
    async (sessionIds: string[], ownerAgentId = selectedAgentRef.current) => {
      if (rejectStaleMutation(ownerAgentId)) return false;
      try {
        await chatApi.batchUnarchiveChats(sessionIds, ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        await fetchSessions(ownerAgentId);
        if (!canMutate(ownerAgentId)) return false;
        messageRef.current.success(
          tRef.current("sessions.archive.batchUnarchiveSuccess", {
            count: sessionIds.length,
            defaultValue: "{{count}} chats unarchived",
          }),
        );
        return true;
      } catch (error) {
        if (!canMutate(ownerAgentId)) return false;
        console.error("Failed to batch unarchive sessions:", error);
        messageRef.current.error(
          tRef.current(
            "sessions.archive.batchUnarchiveFailed",
            "Failed to batch unarchive",
          ),
        );
        return false;
      }
    },
    [canMutate, fetchSessions, rejectStaleMutation],
  );

  const currentState = state.agentId === selectedAgent ? state : null;
  const allSessions = useMemo(
    () => currentState?.sessions ?? [],
    [currentState?.sessions],
  );
  const activeSessions = useMemo(
    () => allSessions.filter((session) => !session.archived),
    [allSessions],
  );
  const archivedSessions = useMemo(
    () => allSessions.filter((session) => session.archived),
    [allSessions],
  );

  return {
    agentId: selectedAgent,
    sessions: activeTab === "active" ? activeSessions : archivedSessions,
    loading: currentState?.loading ?? true,
    error: currentState?.error ?? null,
    refreshSessions: fetchSessions,
    updateSession,
    deleteSession,
    batchDeleteSessions,
    archiveSession,
    unarchiveSession,
    batchArchiveSessions,
    batchUnarchiveSessions,
    activeTab,
    setActiveTab,
    activeCount: activeSessions.length,
    archivedCount: archivedSessions.length,
  };
}
