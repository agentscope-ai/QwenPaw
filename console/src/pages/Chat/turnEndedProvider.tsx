/**
 * Turn-completion plumbing for tool cards.
 *
 * A tool card only sees its own message, and a call block without a result
 * block looks identical whether the tool is still running or the turn was cut
 * short. Neither deciding fact lives on that message:
 *
 * - the response status, which the SDK flips to canceled/failed only while an
 *   SSE loop is alive to observe it, and
 * - whether the chat is still streaming, which stays authoritative even when
 *   the stream dies without a terminal event (dropped connection, proxy kill)
 *   and the user stops the turn afterwards.
 *
 * Both are resolved here and published through ToolCallTurnEndedContext.
 */

import React, { createContext, useContext } from "react";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import { ToolCallTurnEndedContext } from "../../components/Chat/ToolCards/shared/ToolCallTurnContext";

/**
 * Whether the chat is currently receiving a streamed turn.
 *
 * Defaults to streaming: without the provider there is no information about
 * the turn, and reporting a running tool as interrupted is worse than leaving
 * a finished one spinning.
 */
const ChatStreamingContext = createContext(true);

export function ChatStreamingProvider({
  streaming,
  children,
}: {
  streaming: boolean;
  children: React.ReactNode;
}) {
  return (
    <ChatStreamingContext.Provider value={streaming}>
      {children}
    </ChatStreamingContext.Provider>
  );
}

/**
 * Decide whether a response turn can still produce events.
 *
 * `responseDone` is the SDK's terminal run status. It is the fast path but not
 * the only one: a turn stopped after its stream already died keeps an
 * in-progress status forever, so streaming state has the final say.
 */
function resolveTurnEnded(params: {
  responseDone: boolean;
  isLast?: boolean;
  streaming: boolean;
}): boolean {
  if (params.responseDone) return true;
  // Only the newest bubble can be the streaming turn: once another message
  // follows it, no further event can ever land on this response.
  if (params.isLast === false) return true;
  return !params.streaming;
}

/**
 * Publish the turn's completion state to the tool cards inside `children`.
 */
export function ToolCallTurnBoundary({
  data,
  isLast,
  children,
}: {
  data: IAgentScopeRuntimeResponse;
  isLast?: boolean;
  children: React.ReactNode;
}) {
  const streaming = useContext(ChatStreamingContext);
  const turnEnded = resolveTurnEnded({
    responseDone: AgentScopeRuntimeResponseBuilder.maybeDone(data),
    isLast,
    streaming,
  });

  return (
    <ToolCallTurnEndedContext.Provider value={turnEnded}>
      {children}
    </ToolCallTurnEndedContext.Provider>
  );
}
