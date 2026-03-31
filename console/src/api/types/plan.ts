export type SubTaskState = "todo" | "in_progress" | "done" | "abandoned";
export type PlanState = "todo" | "in_progress" | "done" | "abandoned";

export interface SubTask {
  idx: number;
  name: string;
  description: string;
  expected_outcome: string;
  state: SubTaskState;
}

export interface Plan {
  plan_id: string;
  name: string;
  description: string;
  expected_outcome: string;
  state: PlanState;
  subtasks: SubTask[];
  created_at: string;
  updated_at: string;
}

export interface PlanSummary {
  plan_id: string;
  name: string;
  state: PlanState;
  created_at: string;
  subtask_count: number;
  completed_count: number;
}

export interface SubTaskInput {
  name: string;
  description: string;
  expected_outcome: string;
}

export interface CreatePlanRequest {
  name: string;
  description: string;
  expected_outcome: string;
  subtasks: SubTaskInput[];
}

export interface RevisePlanRequest {
  subtask_idx: number;
  action: "add" | "revise" | "delete";
  subtask?: SubTaskInput;
}

export interface FinishPlanRequest {
  state: "done" | "abandoned";
  outcome: string;
}

export interface PlanConfig {
  enabled: boolean;
  max_subtasks: number | null;
  storage_type: "memory" | "file";
  storage_path: string | null;
  agent_managed: boolean;
}
