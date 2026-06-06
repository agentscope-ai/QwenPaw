import { useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useChatStore } from "../stores/chatStore";
import { useSessionStore } from "../stores/sessionStore";
import { useAgentStore } from "../../../stores/agentStore";

export interface UseChatRouterOptions {
  /** Base path for the chat route (e.g. "/chat-v2") */
  basePath: string;
}

export function useChatRouter(
  selectedAgent: string,
  options: UseChatRouterOptions = { basePath: "/chat-v2" },
) {
  const { basePath } = options;
  const { chatId } = useParams<{ chatId?: string }>();
  const navigate = useNavigate();
  const { setLastChatId, getLastChatId } = useAgentStore();

  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const loadSessions = useSessionStore((s) => s.loadSessions);

  // Load sessions on mount and when agent changes
  useEffect(() => {
    loadSessions();
  }, [loadSessions, selectedAgent]);

  // URL → state
  useEffect(() => {
    const target = chatId || null;
    if (target !== activeSessionId) setActiveSession(target);
  }, [chatId]); // eslint-disable-line react-hooks/exhaustive-deps

  // State → URL (skip on initial mount to avoid overwriting the URL before
  // the "URL → state" effect has a chance to restore activeSessionId)
  const isInitialMountRef = useRef(true);
  useEffect(() => {
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false;
      return;
    }
    const urlChatId = chatId || null;
    if (activeSessionId !== urlChatId) {
      const path = activeSessionId
        ? `${basePath}/${activeSessionId}`
        : basePath;
      navigate(path, { replace: true });
    }
  }, [activeSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Agent switch: preserve session per agent
  const prevAgentRef = useRef(selectedAgent);
  useEffect(() => {
    const prev = prevAgentRef.current;
    if (prev !== selectedAgent && prev !== undefined) {
      if (activeSessionId && prev) setLastChatId(prev, activeSessionId);

      const restored = getLastChatId(selectedAgent);
      if (restored) {
        navigate(`${basePath}/${restored}`, { replace: true });
      } else {
        navigate(basePath, { replace: true });
      }
    }
    prevAgentRef.current = selectedAgent;
  }, [selectedAgent]); // eslint-disable-line react-hooks/exhaustive-deps

  return { chatId, navigate };
}
