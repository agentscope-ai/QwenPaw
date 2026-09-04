/**
 * Turn-completion plumbing for tool cards.
 *
 * A tool card only sees its own message, and a call block without a result
 * block looks identical whether the tool is still running or the turn was
 * interrupted: the call message is already `completed` once its arguments
 * finished streaming, and a cancelled turn never sends the result message.
 *
 * Two facts close such a dangling call, both resolved here:
 *
 * - the response reached a terminal status — the SDK flips it to canceled on
 *   stop, and restored history is always terminal;
 * - the user stopped the turn while its stream was already dead, in which case
 *   the SDK never got to write that status (see stoppedTurns).
 *
 * Indirect signals (bubble position, the chat-wide loading flag) are
 * deliberately not used: neither means "this turn can still emit events", and
 * they reported healthy calls as interrupted mid-turn.
 */

import React from "react";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import { ToolCallTurnEndedContext } from "../../components/Chat/ToolCards/shared/ToolCallTurnContext";
import { resolveBackendSessionId } from "../../utils/resolveBackendSessionId";
import { useStoppedTurnsStore } from "./stoppedTurns";

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
  const stoppedSessionId = useStoppedTurnsStore((s) => s.stoppedSessionId);
  // Resolving the session id walks the session list, so let the (usually
  // null) stop signal short-circuit it.
  const turnEnded =
    AgentScopeRuntimeResponseBuilder.maybeDone(data) ||
    (stoppedSessionId !== null &&
      stoppedSessionId === resolveBackendSessionId());

  return (
    <ToolCallTurnEndedContext.Provider value={turnEnded}>
      {children}
    </ToolCallTurnEndedContext.Provider>
  );
}
