import { useEffect } from "react";
import { useAgentStore } from "./agentStore";
import { useCodingModeStore } from "./codingModeStore";
import { useProjectDirectoryStore } from "./projectDirectoryStore";
import { codingModeApi } from "../api/modules/codingMode";
import { projectDirectoryApi } from "../api/modules/projectDirectory";

/**
 * Pull Coding tools and Agent project directory state independently.
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
  const setProjectDir = useProjectDirectoryStore((s) => s.setProjectDir);

  useEffect(() => {
    if (!selectedAgent) return;
    let cancelled = false;
    const startRevision =
      useCodingModeStore.getState().codingModeRevisionByAgent[selectedAgent] ??
      0;
    void Promise.all([codingModeApi.get(), projectDirectoryApi.get()])
      .then(([mode, project]) => {
        if (cancelled) return;
        const currentRevision =
          useCodingModeStore.getState().codingModeRevisionByAgent[
            selectedAgent
          ] ?? 0;
        if (currentRevision === startRevision) {
          setCodingMode(selectedAgent, mode.enabled);
        }
        setProjectDir(
          selectedAgent,
          project.is_workspace_default ? null : project.path,
        );
      })
      .catch((err) => {
        if (cancelled) return;
        // Log so a misconfigured backend is visible — then mark the
        // agent initialized with safe defaults. Without this the
        // Agent configuration stays disabled
        // forever on any GET failure.
        console.warn("Failed to sync coding mode state:", err);
        const currentRevision =
          useCodingModeStore.getState().codingModeRevisionByAgent[
            selectedAgent
          ] ?? 0;
        if (currentRevision === startRevision) {
          setCodingMode(selectedAgent, false);
        }
        setProjectDir(selectedAgent, null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAgent, setCodingMode, setProjectDir]);
}
