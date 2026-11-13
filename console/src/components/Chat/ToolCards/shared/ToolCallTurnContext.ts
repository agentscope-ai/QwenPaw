/**
 * Turn-level run state for tool cards.
 *
 * A tool card only sees its own message. A call block without a result
 * block looks identical whether the tool is still running or the turn was
 * interrupted (stop / error), so a cancelled call would spin forever.
 * The chat page resolves whether the owning turn can still produce events
 * and publishes it here; cards use it to close such dangling calls.
 */

import { createContext, useContext } from "react";

export const ToolCallTurnEndedContext = createContext(false);

/** Whether the response turn owning this tool card already ended. */
export function useToolCallTurnEnded(): boolean {
  return useContext(ToolCallTurnEndedContext);
}
