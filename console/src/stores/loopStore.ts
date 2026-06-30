import { create } from "zustand";
import { request } from "@/api/request";

export type BudgetLevel = "low" | "medium" | "high";

export interface LoopSkillInfo {
  name: string;
  description: string;
  icon?: string;
}

interface LoopState {
  selectedSkill: LoopSkillInfo | null;
  budgetLevel: BudgetLevel;
  chipHighlighted: boolean;

  availableSkills: LoopSkillInfo[];

  setSelectedSkill: (skill: LoopSkillInfo | null) => void;
  setBudgetLevel: (level: BudgetLevel) => void;
  setChipHighlighted: (highlighted: boolean) => void;
  setAvailableSkills: (skills: LoopSkillInfo[]) => void;
}

export const useLoopStore = create<LoopState>((set) => ({
  selectedSkill: null,
  budgetLevel: "medium",
  chipHighlighted: false,
  availableSkills: [],

  setSelectedSkill: (skill) =>
    set({ selectedSkill: skill, chipHighlighted: false }),
  setBudgetLevel: (level) => set({ budgetLevel: level }),
  setChipHighlighted: (highlighted) => set({ chipHighlighted: highlighted }),
  setAvailableSkills: (skills) => set({ availableSkills: skills }),
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
