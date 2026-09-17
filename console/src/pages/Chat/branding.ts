import { ASSISTANT_NAME } from "../../config/brand";

export function resolveAssistantDisplayName(externalNick?: unknown): unknown {
  if (typeof externalNick === "string") {
    return externalNick.trim() || ASSISTANT_NAME;
  }
  return externalNick ?? ASSISTANT_NAME;
}
