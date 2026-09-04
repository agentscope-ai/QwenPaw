export interface SdkCancellationInput {
  session_id: string;
  chatSessionId?: string;
  abort?: () => void;
}

interface CancelSdkChatRequestOptions {
  resolveBackendSessionId: (sessionId: string) => string | null | undefined;
  stopChat: (sessionId: string) => Promise<unknown>;
  onError?: (error: unknown) => void;
}

/** Abort the local SDK stream immediately, then stop the matching backend chat. */
export async function cancelSdkChatRequest(
  input: SdkCancellationInput,
  options: CancelSdkChatRequestOptions,
): Promise<void> {
  // Stop addresses the backend Chat resource (UUID), not its runtime session_id.
  const chatId = input.chatSessionId || input.session_id;
  const backendSessionId = options.resolveBackendSessionId(chatId) || chatId;

  input.abort?.();
  if (!backendSessionId) return;

  try {
    await options.stopChat(backendSessionId);
  } catch (error) {
    options.onError?.(error);
    throw error;
  }
}
