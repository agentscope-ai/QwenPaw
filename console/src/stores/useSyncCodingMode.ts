import { useEffect } from "react";
import { useAgentStore } from "./agentStore";
import { useCodingModeStore } from "./codingModeStore";
import { codingModeApi } from "../api/modules/codingMode";

/**
 * Pull Coding Mode state (enabled + project_dir) from the backend on every
 * selectedAgent change. Backend (agent.json) is the source of truth — the
 * store is in-memory only, so without this hook the UI would show stale or
 * empty state across reloads and tabs.
 *
 * Mount once at a top-level component (e.g. MainLayout) so every route
 * sees a populated store.
 */
export function useSyncCodingMode(): void {
  const { selectedAgent } = useAgentStore();
  const setCodingMode = useCodingModeStore((s) => s.setCodingMode);
  const setProjectDir = useCodingModeStore((s) => s.setProjectDir);

  useEffect(() => {
    if (!selectedAgent) return;
    let cancelled = false;
    void codingModeApi
      .get()
      .then((state) => {
        if (cancelled) return;
        setCodingMode(selectedAgent, state.enabled);
        // null = explicit workspace default; string = specific path.
        setProjectDir(selectedAgent, state.project_dir);
      })
      .catch((err) => {
        if (cancelled) return;
        // Log so a misconfigured backend is visible — then mark the
        // agent initialized with safe defaults. Without this the
        // DefaultRedirect spinner and CodingModeToggle stay disabled
        // forever on any GET failure.
        console.warn("Failed to sync coding mode state:", err);
        setCodingMode(selectedAgent, false);
        setProjectDir(selectedAgent, null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgent, setCodingMode, setProjectDir]);
}
