import { useState, useEffect } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { Session } from "./components/constants";
import { useAgentStore } from "../../../stores/agentStore";
import { useTranslation } from "react-i18next";

export function useSessions() {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const { selectedAgent } = useAgentStore();
  const { message } = useAppMessage();

  const fetchSessions = async () => {
    setLoading(true);
    try {
      const data = await api.listSessions();
      if (data) {
        setSessions(data as Session[]);
      }
    } catch (error) {
      console.error("❌ Failed to load sessions:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;

    const loadSessions = async () => {
      await fetchSessions();
    };

    if (mounted) {
      loadSessions();
    }

    return () => {
      mounted = false;
    };
  }, [selectedAgent]);

  const updateSession = async (sessionId: string, values: Session) => {
    try {
      const result = await api.updateSession(sessionId, values);
      setSessions(sessions.map((s) => (s.id === sessionId ? result : s)));
      message.success(t("sessions.saveSuccess"));
      return true;
    } catch (error) {
      console.error("❌ Failed to save session:", error);
      message.error(t("sessions.saveFailed"));
      return false;
    }
  };

  const deleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      setSessions(sessions.filter((s) => s.id !== sessionId));
      message.success(t("sessions.deleteSuccess"));
      return true;
    } catch (error) {
      console.error("❌ Failed to delete session:", error);
      message.error(t("sessions.deleteFailed"));
      return false;
    }
  };

  const batchDeleteSessions = async (sessionIds: string[]) => {
    try {
      await api.batchDeleteSessions(sessionIds);
      setSessions(sessions.filter((s) => !sessionIds.includes(s.id)));
      message.success(
        t("sessions.batchDeleteSuccess", { count: sessionIds.length }),
      );
      return true;
    } catch (error) {
      console.error("❌ Failed to batch delete sessions:", error);
      message.error(t("sessions.batchDeleteFailed"));
      return false;
    }
  };

  return {
    sessions,
    loading,
    updateSession,
    deleteSession,
    batchDeleteSessions,
  };
}
