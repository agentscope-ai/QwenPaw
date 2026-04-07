import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import sessionApi from "./sessionApi";
import type { IAgentScopeRuntimeWebUISession } from "@agentscope-ai/chat";

/** Sessions from CoPaw backend include extra fields beyond the runtime UI type */
export interface ExtendedChatSession extends IAgentScopeRuntimeWebUISession {
  realId?: string;
  sessionId?: string;
  userId?: string;
  channel?: string;
  createdAt?: string | null;
  meta?: Record<string, unknown>;
  status?: "idle" | "running";
}

interface SessionContextValue {
  sessions: ExtendedChatSession[];
  currentSessionId: string | null;
  setCurrentSessionId: (id: string | null) => void;
  setSessions: (sessions: ExtendedChatSession[]) => void;
  createSession: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  isLoading: boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function useChatSessionContext(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx)
    throw new Error(
      "useChatSessionContext must be used within SessionProvider",
    );
  return ctx;
}

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [sessions, setSessions] = useState<ExtendedChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const refreshSessions = useCallback(async () => {
    setIsLoading(true);
    try {
      const list = await sessionApi.getSessionList();
      setSessions(list as ExtendedChatSession[]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const createSession = useCallback(async () => {
    const newSessionId = Date.now().toString();
    const newSession: ExtendedChatSession = {
      id: newSessionId,
      name: "New Chat",
      sessionId: newSessionId,
      userId: "default",
      channel: "console",
      messages: [],
      meta: {},
    };
    setSessions((prev) => [newSession, ...prev]);
    setCurrentSessionId(newSessionId);
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  const value = useMemo<SessionContextValue>(
    () => ({
      sessions,
      currentSessionId,
      setCurrentSessionId,
      setSessions: setSessions as (s: ExtendedChatSession[]) => void,
      createSession,
      refreshSessions,
      isLoading,
    }),
    [sessions, currentSessionId, createSession, refreshSessions, isLoading],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
};

/** Hook for components that need to sync URL chatId with session context */
export function useSessionUrlSync() {
  const { sessions, currentSessionId, setCurrentSessionId } =
    useChatSessionContext();
  const chatIdRef = useRef<string | null>(null);

  useEffect(() => {
    // Sync currentSessionId to URL would go here if needed
  }, [currentSessionId]);

  return { sessions, currentSessionId, setCurrentSessionId, chatIdRef };
}
