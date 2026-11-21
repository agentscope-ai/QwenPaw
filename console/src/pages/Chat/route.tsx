import { Spin } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { chatApi } from "../../api/modules/chat";
import { useAuthStore } from "../../stores/authStore";
import { useAgentStore } from "../../stores/agentStore";
import { buildChatPath, getSessionIdFromPath } from "../../utils/sessionRoute";
import ChatPage from "./index";
import { findChatAgent } from "./chatAgentResolver";
import sessionApi from "./sessionApi";

/** Resolves a deep-linked chat before mounting ChatPage with the wrong Agent. */
export default function ChatRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  const chatId = useMemo(
    () => getSessionIdFromPath(location.pathname),
    [location.pathname],
  );
  const mode = useAuthStore((state) => state.mode);
  const { selectedAgent, agents, setSelectedAgent, getLastChatId } =
    useAgentStore();
  const navigationAgent =
    location.state?.chatAgentId === selectedAgent ? selectedAgent : null;
  const [resolved, setResolved] = useState<{
    key: string;
    agentId: string;
  } | null>(null);
  const [resolutionError, setResolutionError] = useState<string | null>(null);
  const resolutionKey = `${chatId}:${agents
    .map((agent) => agent.id)
    .join(",")}`;
  const isLiveChat =
    Boolean(chatId) &&
    sessionApi.hasResolvedSessionForAgent(chatId!, selectedAgent);

  useEffect(() => {
    if (mode !== "multi_user" || !chatId) {
      return;
    }
    const key = resolutionKey;
    if (isLiveChat) {
      if (resolved?.key !== key || resolved.agentId !== selectedAgent) {
        setResolved({ key, agentId: selectedAgent });
      }
      return;
    }
    if (resolved?.key === key && resolved.agentId === selectedAgent) return;

    let cancelled = false;
    const errorKey = `${key}:${selectedAgent}`;
    // A deliberate Agent switch or a return from an Agent page must never
    // reinterpret the previous chat UUID as a request to switch back.
    if (
      navigationAgent ||
      (resolved?.key === key && resolved.agentId !== selectedAgent)
    ) {
      void chatApi
        .listChats({ requestContext: { agentId: selectedAgent } })
        .then((chats) => {
          if (cancelled) return;
          if (chats.some((chat) => chat.id === chatId)) {
            setResolved({ key, agentId: selectedAgent });
            return;
          }
          const saved = getLastChatId(selectedAgent);
          const target = chats.some((chat) => chat.id === saved)
            ? saved
            : undefined;
          sessionApi.resetWindowIdentity();
          sessionApi.lastActiveChatId = target ?? null;
          sessionApi.preferredChatId = target ?? null;
          navigate(buildChatPath(target), {
            replace: true,
            state: { chatAgentId: selectedAgent },
          });
        })
        .catch(() => {
          if (!cancelled) setResolutionError(errorKey);
        });
      return () => {
        cancelled = true;
      };
    }
    const controller = new AbortController();
    // A conversation owner keeps history after its Agent is unavailable. The
    // server resolves this stable identity before applying current Agent scope.
    void chatApi
      .getChatSpec(chatId, controller.signal)
      .then(async (spec) => {
        const agentId =
          spec.agent_id ||
          (await findChatAgent(
            chatId,
            agents.map((agent) => agent.id),
            (id) => chatApi.listChats({ requestContext: { agentId: id } }),
          ));
        if (cancelled) return;
        if (!agentId) {
          setResolutionError(errorKey);
          return;
        }
        if (spec.access_role === "owner" && spec.read_only) {
          setSelectedAgent(agentId, { ownedHistory: true });
        } else if (agentId !== selectedAgent) {
          setSelectedAgent(agentId);
        }
        setResolved({ key, agentId });
      })
      .catch(() => {
        if (!cancelled) setResolutionError(errorKey);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [
    agents,
    chatId,
    mode,
    resolutionKey,
    resolved,
    navigationAgent,
    getLastChatId,
    navigate,
    selectedAgent,
    setSelectedAgent,
    isLiveChat,
  ]);

  const isResolving =
    mode === "multi_user" &&
    Boolean(chatId) &&
    !isLiveChat &&
    (resolved?.key !== resolutionKey || resolved.agentId !== selectedAgent);

  if (isResolving) {
    if (resolutionError === `${resolutionKey}:${selectedAgent}`) {
      return (
        <div role="alert">无法确认当前智能体的会话，请刷新页面后重试。</div>
      );
    }
    return <Spin aria-label="loading-chat-agent" />;
  }
  return <ChatPage />;
}
