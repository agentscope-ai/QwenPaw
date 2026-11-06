import type { ChatSubmitInput } from "../../plugins/types/qwenpaw";
import {
  MAX_QUEUE_SIZE,
  useMessageQueueStore,
} from "../../stores/messageQueueStore";
import { buildSubmissionBizParams } from "./submissionBizParams";
import type { SessionIdentity } from "./sessionApi";

interface AdmissionContext {
  active: boolean;
  ready: boolean;
  agentId: string;
  currentSessionId: string;
  queueKey: string;
  resolveIdentity: (id: string) => SessionIdentity;
  prepareQuery: (query: string) => string;
  requestContext: Record<string, unknown>;
  queueFullMessage: string;
  staleMessage: string;
}

/** Synchronous admission captures routing before any queue worker awaits. */
export function enqueuePluginSubmission(
  input: ChatSubmitInput,
  context: AdmissionContext,
): void {
  const identity = context.resolveIdentity(context.currentSessionId);
  const requested = context.resolveIdentity(input.sessionId);
  if (
    !context.active ||
    !context.ready ||
    input.agentId !== context.agentId ||
    !identity.sessionId ||
    !(identity.chatId || identity.sdkSessionId) ||
    (requested.chatId || requested.sdkSessionId) !==
      (identity.chatId || identity.sdkSessionId)
  ) {
    throw new Error(context.staleMessage);
  }
  const store = useMessageQueueStore.getState();
  if (store.getQueue(context.queueKey).length >= MAX_QUEUE_SIZE) {
    throw new Error(context.queueFullMessage);
  }
  store.enqueue(context.queueKey, {
    text: context.prepareQuery(input.query),
    agentId: input.agentId,
    backendSessionId: identity.sessionId,
    userId: identity.userId,
    channel: identity.channel,
    requestContext: context.requestContext,
    bizParams: buildSubmissionBizParams(identity),
  });
}
