import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { CHAT_BASE_PATH } from "../../../utils/sessionRoute";
import { useAgentStore } from "../../../stores/agentStore";
import sessionApi from "../sessionApi";

/**
 * Open the blank composer. The SDK allocates a backend session on first send;
 * opening this page (including after deletion) must not persist an empty chat.
 */
export function useCreateNewSession(): () => Promise<void> {
  const navigate = useNavigate();
  const { setCurrentSessionId } = useChatAnywhereSessionsState();
  return useCallback(async () => {
    sessionApi.finishSessionSwitch();
    sessionApi.lastActiveChatId = null;
    sessionApi.preferredChatId = null;
    const agents = useAgentStore.getState();
    agents.removeLastChatId(agents.selectedAgent);
    setCurrentSessionId(undefined);
    navigate(CHAT_BASE_PATH, { replace: true });
  }, [navigate, setCurrentSessionId]);
}
