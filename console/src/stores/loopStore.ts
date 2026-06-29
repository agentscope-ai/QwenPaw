import { create } from "zustand";
import { request } from "@/api/request";

export type BudgetLevel = "low" | "medium" | "high";

export interface LoopSkillInfo {
  name: string;
  description: string;
  icon?: string;
}

export interface LoopRuntime {
  skillName: string;
  iteration: number;
  maxIterations: number;
  budgetUsedPercent: number;
  statusText: string;
  paused: boolean;
}

interface LoopState {
  selectedSkill: LoopSkillInfo | null;
  budgetLevel: BudgetLevel;
  chipHighlighted: boolean;
  runtime: LoopRuntime | null;

  availableSkills: LoopSkillInfo[];

  setSelectedSkill: (skill: LoopSkillInfo | null) => void;
  setBudgetLevel: (level: BudgetLevel) => void;
  setChipHighlighted: (highlighted: boolean) => void;
  setRuntime: (runtime: LoopRuntime | null) => void;
  setAvailableSkills: (skills: LoopSkillInfo[]) => void;
  pauseLoop: () => void;
  resumeLoop: () => void;
  stopLoop: () => void;
}

export const useLoopStore = create<LoopState>((set) => ({
  selectedSkill: null,
  budgetLevel: "medium",
  chipHighlighted: false,
  runtime: null,
  availableSkills: [],

  setSelectedSkill: (skill) =>
    set({ selectedSkill: skill, chipHighlighted: false }),
  setBudgetLevel: (level) => set({ budgetLevel: level }),
  setChipHighlighted: (highlighted) => set({ chipHighlighted: highlighted }),
  setRuntime: (runtime) => set({ runtime }),
  setAvailableSkills: (skills) => set({ availableSkills: skills }),
  pauseLoop: () =>
    set((state) =>
      state.runtime ? { runtime: { ...state.runtime, paused: true } } : state,
    ),
  resumeLoop: () =>
    set((state) =>
      state.runtime ? { runtime: { ...state.runtime, paused: false } } : state,
    ),
  stopLoop: () => set({ runtime: null }),
}));

interface CommandsResponse {
  commands: Array<{
    name: string;
    description: string;
    category: string;
  }>;
}

export async function fetchAvailableLoopSkills(): Promise<void> {
  try {
    const res = await request<CommandsResponse>(
      "/api/workspace/commands/available",
    );
    const commands = res?.commands ?? [];
    const loopSkills: LoopSkillInfo[] = commands
      .filter((c) => c.category === "plugin")
      .map((c) => ({
        name: c.name,
        description: c.description || c.name,
      }));
    if (loopSkills.length > 0) {
      useLoopStore.getState().setAvailableSkills(loopSkills);
    }
  } catch {
    // Silently fall back to empty list
  }
}
