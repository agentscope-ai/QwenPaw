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

export interface ListMessagesOptions {
  /** Forward cursor: return messages with seq > after (live catch-up). */
  after?: number;
  /** Backward cursor: return the page of messages with seq < before. */
  before?: number;
  /** Return the newest page (initial load); mutually exclusive with after. */
  tail?: boolean;
  limit?: number;
}

export function listMessages(
  projectId: string,
  conversationId: string,
  options: ListMessagesOptions = {},
): Promise<MessagePage> {
  const params = new URLSearchParams();
  const backward = options.tail || options.before != null;
  if (options.tail) params.set("tail", "true");
  if (options.before != null) params.set("before", String(options.before));
  if (!backward && options.after) params.set("after", String(options.after));
  params.set("limit", String(options.limit ?? 50));
  return creatorRequest(
    `/projects/${encodeURIComponent(
      projectId,
    )}/conversations/${encodeURIComponent(conversationId)}` +
      `/messages?${params.toString()}`,
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
