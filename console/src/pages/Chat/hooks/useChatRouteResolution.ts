import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import { useSessionListStore } from "../../../stores/sessionListStore";
import sessionApi, { type SessionOwnerToken } from "../sessionApi";

interface ResolutionState {
  visit: object;
  owner: SessionOwnerToken;
  error: unknown;
}

interface AgentSwitchTarget {
  agentId: string;
  referenceId: string;
  chatId: string;
}

/** Resolve route ownership before the SDK or host uses a persisted Chat. */
export function useChatRouteResolution(
  referenceId: string | undefined,
  selectedAgent: string,
) {
  const [resolution, setResolution] = useState<ResolutionState | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const agentSwitchTarget = useRef<AgentSwitchTarget | null>(null);
  const hasReference = !!referenceId && referenceId !== "new";
  // Persisted SDK display IDs may be runtime aliases of another Chat.
  // Only canonical Chat IDs and genuine local drafts can skip resolution.
  // Subscribe to sidebar publication without rendering for unchanged polls.
  const known = useSessionListStore(() => {
    const identity = sessionApi.getSessionIdentity(referenceId);
    return (
      !!identity.sessionId &&
      (identity.chatId === referenceId ||
        (identity.sdkSessionId === referenceId &&
          sessionApi.isUnresolvedLocalSession(referenceId ?? "")))
    );
  });
  const invalidationVersion = useSessionListStore(() =>
    sessionApi.getRouteResolutionVersion(),
  );
  // Re-entering a link or losing its listed identity requires a fresh result
  // from the first render, before the previous effect can be cleaned up.
  const visit = useMemo(
    () => ({ referenceId, known, retryVersion, invalidationVersion }),
    [referenceId, known, retryVersion, invalidationVersion],
  );
  const visitRef = useRef(visit);
  visitRef.current = visit;
  const currentResolution =
    resolution !== null &&
    resolution.visit === visit &&
    sessionApi.isActiveOwner(resolution.owner)
      ? resolution
      : null;
  const error = currentResolution?.error ?? null;
  const resolved = known || (currentResolution !== null && error === null);

  useEffect(() => {
    if (!referenceId || referenceId === "new" || known) return;
    const controller = new AbortController();
    const owner = sessionApi.getActiveOwner();
    const isCurrent = () =>
      !controller.signal.aborted &&
      visitRef.current === visit &&
      sessionApi.isActiveOwner(owner);

    void api
      .resolveChat(referenceId, {
        currentAgentId: selectedAgent,
        signal: controller.signal,
      })
      .then(({ agent_id: agentId, chat }) => {
        if (!isCurrent()) return;
        if (agentId !== selectedAgent) {
          agentSwitchTarget.current = {
            agentId,
            referenceId,
            chatId: chat.id,
          };
          useAgentStore.getState().setSelectedAgent(agentId);
        }
        const nextOwner = sessionApi.getActiveOwner();
        sessionApi.registerResolvedChat(chat, nextOwner);
        setResolution({ visit, owner: nextOwner, error: null });
      })
      .catch((error: unknown) => {
        if (isCurrent()) setResolution({ visit, owner, error });
      });

    return () => controller.abort();
    // Losing a listed Chat's identity requires resolution again. Ordinary
    // list refreshes leave this boolean unchanged and keep requests intact.
  }, [referenceId, selectedAgent, known, visit]);

  const retry = useCallback(() => {
    setResolution(null);
    setRetryVersion((version) => version + 1);
  }, []);

  return {
    blocked: hasReference && (!resolved || error !== null),
    error,
    retry,
    agentSwitchTarget,
  };
}
