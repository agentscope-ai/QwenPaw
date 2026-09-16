import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useChatAnywhereSessions } from "@agentscope-ai/chat";
import sessionApi from "../sessionApi";
import { resetConversationModelScope } from "../conversationModel";
import { CHAT_BASE_PATH } from "../../../utils/sessionRoute";
import {
  isAgentHistoricalReadOnly,
  useAgentStore,
} from "../../../stores/agentStore";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";

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
  const { message } = useAppMessage();
  const { t } = useTranslation();
  const historicalReadOnly = useAgentStore((state) =>
    isAgentHistoricalReadOnly(state.agents, state.selectedAgent),
  );
  return useCallback(async () => {
    if (historicalReadOnly) {
      message.warning(t("chat.historicalReadOnlyNotice"));
      return;
    }
    sessionApi.preferredChatId = null;
    sessionApi.lastNavigatedChatId = null;
    sessionApi.userInitiatedCreate = true;
    // Clear the mounted conversation before awaiting SDK session creation.
    // The route changes during creation, so a reset dispatched only afterward
    // can be missed by the old Chat instance and leave its messages visible.
    window.dispatchEvent(new Event("qwenpaw:new-chat-reset"));
    await createSession();
    // sessionApi announces the new local session on the next task so the SDK
    // can clear its message state first. Wait for that announcement to remove
    // the persisted previous-chat restore target before resetting the view.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    resetConversationModelScope();
    navigate(CHAT_BASE_PATH, { replace: true });
    window.dispatchEvent(new Event("qwenpaw:new-chat-reset"));
    window.dispatchEvent(new Event("model-switched"));
  }, [createSession, historicalReadOnly, message, navigate, t]);
}
