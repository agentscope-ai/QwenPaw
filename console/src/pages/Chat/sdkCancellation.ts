export interface SdkCancellationInput {
  session_id: string;
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
  const backendSessionId =
    options.resolveBackendSessionId(input.session_id) || input.session_id;

  input.abort?.();
  if (!backendSessionId) return;

  try {
    await options.stopChat(backendSessionId);
  } catch (error) {
    options.onError?.(error);
  }
}
