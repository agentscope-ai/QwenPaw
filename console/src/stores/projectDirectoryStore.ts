import { create } from "zustand";
import { useAgentStore } from "./agentStore";

interface ProjectDirectoryState {
  projectDirByAgent: Record<string, string | null>;
  setProjectDir: (agentId: string, path: string | null) => void;
}

export const useProjectDirectoryStore = create<ProjectDirectoryState>(
  (set) => ({
    projectDirByAgent: {},
    setProjectDir: (agentId, path) =>
      set((state) => ({
        projectDirByAgent: {
          ...state.projectDirByAgent,
          [agentId]: path,
        },
      })),
  }),
);

export function useProjectDir(): {
  projectDir: string | null | undefined;
  setProjectDir: (path: string | null) => void;
} {
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const projectDir = useProjectDirectoryStore(
    (state) => state.projectDirByAgent[selectedAgent],
  );
  const setProjectDir = useProjectDirectoryStore(
    (state) => state.setProjectDir,
  );
  return {
    projectDir,
    setProjectDir: (path) => setProjectDir(selectedAgent, path),
  };
}
