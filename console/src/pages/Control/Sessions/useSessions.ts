import { useState, useEffect } from "react";
import { message } from "@agentscope-ai/design";
import api from "../../../api";
import type { Session } from "./components/constants";
import { useAgentStore } from "../../../stores/agentStore";

export function useSessions() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const { selectedAgent } = useAgentStore();

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
      message.success("Saved successfully");
      return true;
    } catch (error) {
      console.error("❌ Failed to save session:", error);
      message.error("Save failed");
      return false;
    }
  };

  const deleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      setSessions(sessions.filter((s) => s.id !== sessionId));
      message.success("Deleted successfully");
      return true;
    } catch (error) {
      console.error("❌ Failed to delete session:", error);
      message.error("Failed to delete");
      return false;
    }
  };

  const batchDeleteSessions = async (sessionIds: string[]) => {
    try {
      await api.batchDeleteSessions(sessionIds);
      setSessions(sessions.filter((s) => !sessionIds.includes(s.id)));
      message.success(`Successfully deleted ${sessionIds.length} session(s)`);
      return true;
    } catch (error) {
      console.error("❌ Failed to batch delete sessions:", error);
      message.error("Failed to batch delete sessions");
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
