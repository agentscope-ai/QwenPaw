import type { ChatSubmitInput, Disposable } from "../types/qwenpaw";
import i18n from "../../i18n";

type SubmitHandler = (input: ChatSubmitInput) => void | Promise<void>;
let activeHandler: SubmitHandler | undefined;

/** Only the active Chat page binds a handler. Old cleanups cannot remove a newer one. */
export function bindChatSubmit(handler: SubmitHandler): Disposable {
  activeHandler = handler;
  return {
    dispose() {
      if (activeHandler === handler) activeHandler = undefined;
    },
  };
}

export async function submitChat(
  pluginId: string,
  input: ChatSubmitInput,
): Promise<void> {
  if (!pluginId || !input.query?.trim() || !input.agentId || !input.sessionId) {
    throw new Error("A plugin, message, Agent and session are required.");
  }
  const handler = activeHandler;
  if (!handler) throw new Error(i18n.t("chat.pluginSubmission.notReady"));
  await handler({ ...input, query: input.query.trim() });
}
