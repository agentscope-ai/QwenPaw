import { chatApi } from "../../../api/modules/chat";

export type SessionViewInspection =
  | { kind: "chat" }
  | { kind: "empty" };

export async function inspectSessionForView(
  sessionId: string,
): Promise<SessionViewInspection> {
  const history = await chatApi.getChat(sessionId);
  return history.messages?.length > 0 ? { kind: "chat" } : { kind: "empty" };
}
