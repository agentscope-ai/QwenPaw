import { useEffect, useRef } from "react";

import { chatApi } from "../../../api/modules/chat";

const DEFAULT_INTERVAL_MS = 3000;

function isConversationUnavailable(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /chat not found|conversation not found|not_found/i.test(message);
}

interface SharedConversationAccessGuardOptions {
  conversationId?: string;
  enabled: boolean;
  intervalMs?: number;
  onRevoked: () => void;
}

/**
 * Revalidates an already-open viewer conversation. List polling alone is not
 * sufficient because the drawer may be closed and a filtered list can omit a
 * valid conversation. A direct read check makes revocation authoritative.
 */
export function useSharedConversationAccessGuard({
  conversationId,
  enabled,
  intervalMs = DEFAULT_INTERVAL_MS,
  onRevoked,
}: SharedConversationAccessGuardOptions): void {
  const onRevokedRef = useRef(onRevoked);
  onRevokedRef.current = onRevoked;

  useEffect(() => {
    if (!enabled || !conversationId) return;

    let disposed = false;
    let checking = false;
    let revoked = false;

    const verifyAccess = async () => {
      if (disposed || checking || revoked) return;
      checking = true;
      try {
        await chatApi.getChat(conversationId);
      } catch (error) {
        if (!disposed && isConversationUnavailable(error)) {
          revoked = true;
          onRevokedRef.current();
        }
      } finally {
        checking = false;
      }
    };

    void verifyAccess();
    const timer = window.setInterval(() => {
      void verifyAccess();
    }, intervalMs);

    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [conversationId, enabled, intervalMs]);
}
