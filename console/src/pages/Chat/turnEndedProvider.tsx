/**
 * Turn-completion plumbing for tool cards.
 *
 * A tool card only sees its own message, and a call block without a result
 * block looks identical whether the tool is still running or the turn was
 * interrupted: the call message is already `completed` once its arguments
 * finished streaming, and a cancelled turn never sends the result message.
 *
 * The deciding fact lives on the response instead — the SDK flips it to
 * canceled/failed on interruption, and restored history is always terminal.
 * It is published here so cards can close their dangling calls.
 *
 * Only the response status is used. Indirect signals (bubble position, the
 * chat-wide loading flag) do not reliably mean "this turn can still emit
 * events" and reported healthy calls as interrupted mid-turn.
 */

import React from "react";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import { ToolCallTurnEndedContext } from "../../components/Chat/ToolCards/shared/ToolCallTurnContext";

/**
 * Publish the turn's completion state to the tool cards inside `children`.
 */
export function ToolCallTurnBoundary({
  data,
  children,
}: {
  data: IAgentScopeRuntimeResponse;
  children: React.ReactNode;
}) {
  const turnEnded = AgentScopeRuntimeResponseBuilder.maybeDone(data);

  return (
    <ToolCallTurnEndedContext.Provider value={turnEnded}>
      {children}
    </ToolCallTurnEndedContext.Provider>
  );
}
