import type {
  IAgentScopeRuntimeWebUIMessage,
  IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";

type RuntimeMessagesController = IAgentScopeRuntimeWebUIRef["messages"];

/**
 * Replace the SDK message state with one canonical server snapshot.
 * The SDK ref exposes remove/update operations rather than setMessages;
 * React queues these updates in order, so each snapshot starts from empty.
 */
export function replaceRuntimeMessageSnapshot(
  controller: RuntimeMessagesController | null | undefined,
  messages: IAgentScopeRuntimeWebUIMessage[],
): void {
  if (!controller) return;
  controller.removeAllMessages();
  messages.forEach((message) => controller.updateMessage(message));
}
