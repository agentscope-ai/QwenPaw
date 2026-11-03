import { PLUGIN_ID } from "./host";
import type { ActionEvent } from "@openuidev/react-lang";
import type { QwenPawWindowNamespace } from "./qwenpaw-host";

/** Explicitly submitted values become ordinary, visible model context. */
export function actionMessage(event: ActionEvent): string {
  const text = event.humanFriendlyMessage?.trim();
  if (!text) throw new Error("This action has no message to submit.");
  const values: Record<string, unknown> = {};
  if (event.params?.context !== undefined)
    values.context = event.params.context;
  // OpenUI also supplies its entire local store on ordinary button clicks.
  // Only submit fields from an explicitly scoped Form; $state is conveyed
  // through @ToAssistant's message/context, never silently dumped wholesale.
  const form = event.formName && event.formState?.[event.formName];
  if (form && typeof form === "object" && !Array.isArray(form)) {
    values.form = Object.fromEntries(
      Object.entries(form).map(([name, field]) => [
        name,
        field &&
        typeof field === "object" &&
        "componentType" in field &&
        "value" in field
          ? field.value
          : field,
      ]),
    );
  }
  return Object.keys(values).length
    ? `${text}\n\n${JSON.stringify(values, null, 2)}`
    : text;
}

export async function dispatchAction(
  api: QwenPawWindowNamespace,
  scope: { agentId: string; sessionId: string },
  event: ActionEvent,
): Promise<void> {
  switch (event.type) {
    case "continue_conversation":
      await api.chat.submit(PLUGIN_ID, {
        ...scope,
        query: actionMessage(event),
      });
      return;
    case "open_url": {
      const url = new URL(String(event.params?.url || ""));
      if (url.protocol !== "https:" && url.protocol !== "http:") {
        throw new Error("Only HTTP(S) links are supported.");
      }
      api.host.openExternalLink(url.href);
      return;
    }
    default:
      throw new Error(`Unsupported OpenUI action: ${event.type}`);
  }
}
