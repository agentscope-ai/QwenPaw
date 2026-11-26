export interface SdkCancellationInput {
  session_id: string;
  chatSessionId?: string;
  abort?: () => void;
}

interface CancelSdkChatRequestOptions {
  resolveBackendSessionId: (sessionId: string) => string | null | undefined;
  stopChat: (sessionId: string) => Promise<{ stopped: boolean }>;
  onError?: (error: unknown) => void;
}

/** Request backend cancellation and let the SDK consume the original SSE terminal. */
export async function cancelSdkChatRequest(
  input: SdkCancellationInput,
  options: CancelSdkChatRequestOptions,
): Promise<boolean> {
  // Stop addresses the backend Chat resource (UUID), not its runtime session_id.
  const chatId = input.chatSessionId || input.session_id;
  const backendSessionId = options.resolveBackendSessionId(chatId) || chatId;

  if (!backendSessionId)
    throw new Error("Missing chat identity for cancellation");

  try {
    const result = await options.stopChat(backendSessionId);
    return result.stopped;
  } catch (error) {
    options.onError?.(error);
    throw error;
  }
}
