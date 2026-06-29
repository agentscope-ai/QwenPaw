import { create } from "zustand";

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
  availableSkills: [
    {
      name: "ralph",
      description: "持久完成循环 — 分解任务并逐个完成",
    },
    {
      name: "ultrawork",
      description: "并行委派 — 分解 todos 逐个完成",
    },
    {
      name: "deep-interview",
      description: "苏格拉底式提问 — 深挖需求模糊点",
    },
    {
      name: "autopilot",
      description: "多阶段自治 — 自动规划并执行",
    },
    {
      name: "browser-mission",
      description: "浏览器自动化 — 操控浏览器完成任务",
    },
  ],

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
