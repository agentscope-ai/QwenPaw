import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import { CHAT_BASE_PATH } from "../../../utils/sessionRoute";
import sessionApi from "../sessionApi";

/**
 * Returns a stable async function that creates a new blank chat session.
 *
 * Navigates to the Chat base path before calling the library's
 * createSession so the controlled session option releases the previous Chat
 * UUID before the SDK allocates the new local session.
 */
export function useCreateNewSession(): () => Promise<void> {
  const navigate = useNavigate();
  const { createSession } = useChatAnywhereSessions();
  return useCallback(async () => {
    sessionApi.finishSessionSwitch();
    navigate(CHAT_BASE_PATH, { replace: true });
    await createSession();
  }, [navigate, createSession]);
}
