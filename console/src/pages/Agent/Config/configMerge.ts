import type { AgentsRunningConfig } from "@/api/types";
import type { ToolExecutionLevel } from "./components/ToolExecutionLevelCard";

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function mergeValue(base: unknown, override: unknown): unknown {
  if (!isPlainObject(base) || !isPlainObject(override)) {
    return override;
  }
  const merged: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(override)) {
    merged[key] = mergeValue(base[key], value);
  }
  return merged;
}

export function mergeRunningConfig(
  original: AgentsRunningConfig,
  formValues: Partial<AgentsRunningConfig>,
  approvalLevel: ToolExecutionLevel,
): AgentsRunningConfig {
  const merged = mergeValue(original, formValues) as AgentsRunningConfig;
  const iterationLimit = formValues.loop?.iteration?.max_iterations;
  return {
    ...merged,
    approval_level: approvalLevel,
    max_iters: iterationLimit ?? original.max_iters,
  };
}
