import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import sessionApi from "../sessionApi";
import { useCodingMode } from "../../../stores/codingModeStore";
import { buildBasePath } from "../../../utils/sessionRoute";

/**
 * Returns a stable async function that creates a new blank chat session.
 *
 * Navigates to the base path (/chat or /coding) BEFORE calling the library's
 * createSession so that ChatSessionInitializer sees chatId=undefined and does
 * not re-apply the previous session, which would race against the new session
 * creation.
 */
export function useCreateNewSession(): () => Promise<void> {
  const navigate = useNavigate();
  const { createSession } = useChatAnywhereSessions();
  const { codingMode } = useCodingMode();

  return useCallback(async () => {
    const mode = codingMode ? "coding" : "chat";
    navigate(buildBasePath(mode), { replace: true });
    sessionApi.userInitiatedCreate = true;
    await createSession();
  }, [navigate, createSession, codingMode]);
}
