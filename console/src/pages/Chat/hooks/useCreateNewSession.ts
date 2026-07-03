import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import sessionApi from "../sessionApi";
import { useCodingMode } from "../../../stores/codingModeStore";
import { buildBasePath } from "../../../utils/sessionRoute";

/**
 * Returns a stable async function that creates a new blank chat session.
 *
 * Marks the blank-create intent before navigating to the base path, otherwise
 * ChatSessionInitializer can briefly see /chat with historical sessions and
 * restore the latest conversation before createSession has inserted the local
 * placeholder.
 */
export function useCreateNewSession(): () => Promise<void> {
  const navigate = useNavigate();
  const { createSession } = useChatAnywhereSessions();
  const { codingMode } = useCodingMode();

  return useCallback(async () => {
    const mode = codingMode ? "coding" : "chat";
    sessionApi.suppressBaseAutoSelect = true;
    sessionApi.userInitiatedCreate = true;
    sessionApi.preferredChatId = null;
    sessionApi.lastActiveChatId = null;
    navigate(buildBasePath(mode), { replace: true });
    await createSession();
  }, [navigate, createSession, codingMode]);
}
