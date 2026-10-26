import { useEffect } from "react";

import { sessionThinkingApi } from "@/features/thinking/sessionThinkingApi";
import { isSessionModelChangedFor } from "@/features/session-settings/sessionModelEvents";

/** Keep the session decision setting available while the Advisor model pill
 * replaces SessionThinking in the composer. */
export function useAdvisorDecisionAvailability({
  active,
  agentId,
  sessionId,
  chatId,
  onChange,
}: {
  active: boolean;
  agentId: string;
  sessionId: string;
  chatId?: string | null;
  onChange: (enabled: boolean | undefined) => void;
}) {
  useEffect(() => {
    if (!active) return;

    let disposed = false;
    let revision = 0;
    onChange(undefined);
    const load = () => {
      const current = ++revision;
      void sessionThinkingApi
        .get(agentId, chatId, sessionId)
        .then((view) => {
          if (!disposed && revision === current)
            onChange(view.decision?.enabled);
        })
        .catch(() => {
          if (!disposed && revision === current) onChange(undefined);
        });
    };

    const refresh = (event: Event) => {
      if (isSessionModelChangedFor(event, { agentId, sessionId, chatId }))
        load();
    };

    load();
    window.addEventListener("session-model-changed", refresh);
    return () => {
      disposed = true;
      window.removeEventListener("session-model-changed", refresh);
    };
  }, [active, agentId, sessionId, chatId, onChange]);
}
