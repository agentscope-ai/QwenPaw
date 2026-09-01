import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  useChatAnywhereSessions,
  useChatAnywhereSessionsState,
} from "@agentscope-ai/chat";
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
  const { createSession, changeCurrentSessionId } = useChatAnywhereSessions();
  const { setCurrentSessionId } = useChatAnywhereSessionsState();
  return useCallback(async () => {
    // Let the empty-chat route commit before the SDK publishes its updated
    // session list. Otherwise ChatSessionInitializer can still run with the
    // previous render's chatId and reactivate that conversation.
    navigate(CHAT_BASE_PATH, { replace: true });
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    setCurrentSessionId(undefined);
    sessionApi.userInitiatedCreate = true;
    const createdSessionId = await createSession();
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    if (createdSessionId) {
      changeCurrentSessionId(createdSessionId);
    }
  }, [changeCurrentSessionId, setCurrentSessionId, navigate, createSession]);
}
