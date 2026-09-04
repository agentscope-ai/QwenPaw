import { useEffect } from "react";
import { useAgentStore } from "./agentStore";
import { DISABLED_ADVISOR_MODE, useAdvisorModeStore } from "./advisorModeStore";
import { advisorModeApi } from "../api/modules/advisorMode";

/**
 * Pull Advisor Mode state for the selected agent from the backend.
 * agent.json is the source of truth — the store is in-memory only, so
 * without this hook the UI would show stale or empty state across reloads
 * and tabs.
 *
 * Mounted by the components that show Advisor state (the setup panel in
 * the chat and the Advisor loop template), so nothing is fetched until
 * one of them renders.
 */
export function useSyncAdvisorMode(): void {
  const { selectedAgent } = useAgentStore();
  const setAdvisorMode = useAdvisorModeStore((s) => s.setAdvisorMode);

  useEffect(() => {
    if (!selectedAgent) return;
    let cancelled = false;
    const startRevision =
      useAdvisorModeStore.getState().advisorModeRevisionByAgent[
        selectedAgent
      ] ?? 0;
    const stillCurrent = () =>
      (useAdvisorModeStore.getState().advisorModeRevisionByAgent[
        selectedAgent
      ] ?? 0) === startRevision;
    void advisorModeApi
      .get()
      .then((state) => {
        if (cancelled || !stillCurrent()) return;
        setAdvisorMode(selectedAgent, state);
      })
      .catch((err) => {
        if (cancelled) return;
        // Log so a misconfigured backend is visible — then mark the agent
        // initialized with safe defaults so the UI does not stay disabled
        // forever on any GET failure.
        console.warn("Failed to sync advisor mode state:", err);
        if (stillCurrent()) {
          setAdvisorMode(selectedAgent, DISABLED_ADVISOR_MODE);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgent, setAdvisorMode]);
}
