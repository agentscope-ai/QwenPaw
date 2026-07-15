import { useState, useEffect, useCallback, useMemo } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import { chatApi } from "../../../api/modules/chat";
import type { ChatUpdateRequest } from "../../../api/types";
import type { Session } from "./components/constants";
import { useAgentStore } from "../../../stores/agentStore";
import { useTranslation } from "react-i18next";

export function useSessions() {
  const { t } = useTranslation();
  const [allSessions, setAllSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"active" | "archived">("active");
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await chatApi.listChats();
      if (data) {
        setAllSessions(data as Session[]);
      }
    } catch (error) {
      console.error("Failed to load sessions:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions, selectedAgent]);

  const activeSessions = useMemo(
    () => allSessions.filter((s) => !s.archived),
    [allSessions],
  );

  const archivedSessions = useMemo(
    () => allSessions.filter((s) => s.archived),
    [allSessions],
  );

  const sessions = activeTab === "active" ? activeSessions : archivedSessions;
  const activeCount = activeSessions.length;
  const archivedCount = archivedSessions.length;

  const updateSession = async (
    sessionId: string,
    values: ChatUpdateRequest,
  ) => {
    try {
      const result = await api.updateSession(sessionId, values);
      setAllSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? result : s)),
      );
      message.success(t("sessions.saveSuccess"));
      return true;
    } catch (error) {
      console.error("Failed to save session:", error);
      message.error(t("sessions.saveFailed"));
      return false;
    }
  };

  const deleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      setAllSessions((prev) => prev.filter((s) => s.id !== sessionId));
      message.success(t("sessions.deleteSuccess"));
      return true;
    } catch (error) {
      console.error("Failed to delete session:", error);
      message.error(t("sessions.deleteFailed"));
      return false;
    }
  };

  const batchDeleteSessions = async (sessionIds: string[]) => {
    try {
      await api.batchDeleteSessions(sessionIds);
      setAllSessions((prev) => prev.filter((s) => !sessionIds.includes(s.id)));
      message.success(
        t("sessions.batchDeleteSuccess", { count: sessionIds.length }),
      );
      return true;
    } catch (error) {
      console.error("Failed to batch delete sessions:", error);
      message.error(t("sessions.batchDeleteFailed"));
      return false;
    }
  };

  const archiveSession = async (sessionId: string) => {
    try {
      const updated = await chatApi.archiveChat(sessionId);
      setAllSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? (updated as Session) : s)),
      );
      message.success(t("sessions.archive.successHint"));
      return true;
    } catch (error) {
      console.error("Failed to archive session:", error);
      message.error(t("sessions.archive.failed", "Failed to archive"));
      return false;
    }
  };

  const unarchiveSession = async (sessionId: string) => {
    try {
      const updated = await chatApi.unarchiveChat(sessionId);
      setAllSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? (updated as Session) : s)),
      );
      message.success(
        t("sessions.archive.unarchiveSuccess", "Chat unarchived"),
      );
      return true;
    } catch (error) {
      console.error("Failed to unarchive session:", error);
      message.error(
        t("sessions.archive.unarchiveFailed", "Failed to unarchive"),
      );
      return false;
    }
  };

  const batchArchiveSessions = async (sessionIds: string[]) => {
    try {
      await chatApi.batchArchiveChats(sessionIds);
      await fetchSessions();
      message.success(
        t("sessions.archive.batchSuccess", {
          count: sessionIds.length,
          defaultValue: "{{count}} chats archived",
        }),
      );
      return true;
    } catch (error) {
      console.error("Failed to batch archive sessions:", error);
      message.error(
        t("sessions.archive.batchFailed", "Failed to batch archive"),
      );
      return false;
    }
  };

  const batchUnarchiveSessions = async (sessionIds: string[]) => {
    try {
      await chatApi.batchUnarchiveChats(sessionIds);
      await fetchSessions();
      message.success(
        t("sessions.archive.batchUnarchiveSuccess", {
          count: sessionIds.length,
          defaultValue: "{{count}} chats unarchived",
        }),
      );
      return true;
    } catch (error) {
      console.error("Failed to batch unarchive sessions:", error);
      message.error(
        t("sessions.archive.batchUnarchiveFailed", "Failed to batch unarchive"),
      );
      return false;
    }
  };

  return {
    sessions,
    loading,
    updateSession,
    deleteSession,
    batchDeleteSessions,
    archiveSession,
    unarchiveSession,
    batchArchiveSessions,
    batchUnarchiveSessions,
    activeTab,
    setActiveTab,
    activeCount,
    archivedCount,
  };
}
