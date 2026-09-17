import type {
  ConversationCreated,
  ConversationPage,
  CreatorSessionResponse,
  MessageAccepted,
  MessagePage,
  SendCreatorMessageRequest,
} from "@/contracts/creator";
import { creatorRequest, jsonBody, newClientId } from "./client";
import i18n from "@/i18n";

export function getCreatorSession(
  projectId: string,
): Promise<CreatorSessionResponse> {
  return creatorRequest(`/projects/${encodeURIComponent(projectId)}/session`);
}

export function listConversations(
  projectId: string,
  cursor?: number,
): Promise<ConversationPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return creatorRequest(
    `/projects/${encodeURIComponent(projectId)}/conversations${query}`,
  );
}

export function createConversation(
  projectId: string,
  clientRequestId = newClientId("conversation"),
): Promise<ConversationCreated> {
  return creatorRequest(
    `/projects/${encodeURIComponent(projectId)}/conversations`,
    {
      method: "POST",
      headers: { "Idempotency-Key": clientRequestId },
      body: jsonBody({ title: i18n.t("api.newConversation") }),
    },
  );
}

export function listMessages(
  projectId: string,
  conversationId: string,
  after = 0,
  limit = 50,
): Promise<MessagePage> {
  return creatorRequest(
    `/projects/${encodeURIComponent(
      projectId,
    )}/conversations/${encodeURIComponent(conversationId)}` +
      `/messages?after=${after}&limit=${limit}`,
  );
}

export function sendCreatorMessage(
  projectId: string,
  request: SendCreatorMessageRequest,
): Promise<MessageAccepted> {
  return creatorRequest(`/projects/${encodeURIComponent(projectId)}/messages`, {
    method: "POST",
    headers: { "Idempotency-Key": request.clientMessageId },
    body: jsonBody(request),
  });
}

export function interruptCreator(projectId: string): Promise<{
  creatorSessionId: string;
  status: string;
  stopRequested: boolean;
}> {
  const id = newClientId("interrupt");
  return creatorRequest(
    `/projects/${encodeURIComponent(projectId)}/interrupt`,
    {
      method: "POST",
      headers: { "Idempotency-Key": id },
      body: jsonBody({}),
    },
  );
}
