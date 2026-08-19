import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import sessionApi from "../sessionApi";
import { CHAT_BASE_PATH } from "../../../utils/sessionRoute";

/**
 * Returns a stable async function that creates a new blank chat session.
 *
 * Navigates to the Chat base path before calling the library's
 * createSession so that ChatSessionInitializer sees chatId=undefined and does
 * not re-apply the previous session, which would race against the new session
 * creation.
 */
export function useCreateNewSession(): () => Promise<void> {
  const navigate = useNavigate();
  const { createSession } = useChatAnywhereSessions();
  return useCallback(async () => {
    navigate(CHAT_BASE_PATH, { replace: true });
    sessionApi.userInitiatedCreate = true;
    await createSession();
  }, [navigate, createSession]);
}
