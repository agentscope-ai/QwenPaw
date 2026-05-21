import { create } from "zustand";
import { persist } from "zustand/middleware";
import { useAgentStore } from "./agentStore";

export interface TodoItem {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "done" | "cancelled";
}

interface CodingModeState {
  /** Whether Coding Mode is active per agentId */
  codingModeByAgent: Record<string, boolean>;
  /** Live TODO list, keyed by agentId */
  todosByAgent: Record<string, TodoItem[]>;
  /**
   * Active coding project directory path, keyed by agentId.
   * Key absent / undefined → never selected (show picker on next toggle).
   * null → user explicitly chose the default workspace (skip picker).
   * string → specific project directory.
   */
  projectDirByAgent: Record<string, string | null>;

  setCodingMode: (agentId: string, enabled: boolean) => void;
  setTodos: (agentId: string, todos: TodoItem[]) => void;
  setProjectDir: (agentId: string, path: string | null) => void;
}

export const useCodingModeStore = create<CodingModeState>()(
  persist<CodingModeState>(
    (set) => ({
      codingModeByAgent: {},
      todosByAgent: {},
      projectDirByAgent: {},

      setCodingMode: (agentId: string, enabled: boolean) =>
        set((state: CodingModeState) => ({
          codingModeByAgent: { ...state.codingModeByAgent, [agentId]: enabled },
        })),

      setTodos: (agentId: string, todos: TodoItem[]) =>
        set((state: CodingModeState) => ({
          todosByAgent: { ...state.todosByAgent, [agentId]: todos },
        })),

      setProjectDir: (agentId: string, path: string | null) =>
        set((state: CodingModeState) => ({
          projectDirByAgent: { ...state.projectDirByAgent, [agentId]: path },
        })),
    }),
    {
      name: "qwenpaw-coding-mode",
    },
  ),
);

/** Convenience hook: coding mode status for the currently selected agent */
export function useCodingMode(): {
  codingMode: boolean;
  setCodingMode: (enabled: boolean) => void;
} {
  const { selectedAgent } = useAgentStore();
  const { codingModeByAgent, setCodingMode } = useCodingModeStore();
  return {
    codingMode: codingModeByAgent[selectedAgent] ?? false,
    setCodingMode: (enabled: boolean) => setCodingMode(selectedAgent, enabled),
  };
}

/** Convenience hook: todos for the currently selected agent */
export function useCurrentTodos(): TodoItem[] {
  const { selectedAgent } = useAgentStore();
  const { todosByAgent } = useCodingModeStore();
  return todosByAgent[selectedAgent] ?? [];
}

/** Convenience hook: coding project directory for the currently selected agent.
 *
 * Returns `undefined` when the user has never chosen a project (show picker),
 * `null` when they explicitly chose the default workspace (skip picker),
 * or a `string` path when a specific project is active.
 */
export function useProjectDir(): {
  projectDir: string | null | undefined;
  setProjectDir: (path: string | null) => void;
} {
  const { selectedAgent } = useAgentStore();
  const { projectDirByAgent, setProjectDir } = useCodingModeStore();
  return {
    // Do NOT fall back to null here – undefined means "never selected"
    projectDir: projectDirByAgent[selectedAgent],
    setProjectDir: (path: string | null) => setProjectDir(selectedAgent, path),
  };
}
