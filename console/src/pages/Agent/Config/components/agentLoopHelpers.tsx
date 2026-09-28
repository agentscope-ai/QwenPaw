import type { ReactNode } from "react";
import {
  Repeat,
  Shield,
  Gauge,
  Clock3,
  Wrench,
  CheckCircle,
  ListChecks,
} from "lucide-react";
import { arrayMove } from "@dnd-kit/sortable";
import type {
  CustomGateType,
  CustomLoopModeConfig,
  GateInstanceConfig,
} from "@/api/types";
export type GateDefinition = {
  type: CustomGateType;
  title: string;
  titleKey: string;
  description: string;
  descriptionKey: string;
  icon: ReactNode;
  defaults: Record<string, unknown>;
  exclusiveGroup?: string;
};

export const GATE_DEFINITIONS: GateDefinition[] = [
  {
    type: "iteration",
    title: "Iteration limit",
    titleKey: "agentConfig.loopMode.iterationGateTitle",
    description: "Stop after a fixed number of loop iterations.",
    descriptionKey: "agentConfig.loopMode.iterationGateDescription",
    icon: <Repeat size={15} />,
    defaults: { max_iterations: 40 },
  },
  {
    type: "doom_loop",
    title: "Repetition protection",
    titleKey: "agentConfig.loopMode.doomGateTitle",
    description: "Detect repeated tool calls and change strategy.",
    descriptionKey: "agentConfig.loopMode.doomGateDescription",
    icon: <Shield size={15} />,
    defaults: {
      window_size: 3,
      similarity_threshold: 1,
      stages: [
        {
          after: 3,
          action: "modify_prompt",
          prompt: "Change strategy instead of repeating the same action.",
        },
        {
          after: 5,
          action: "stop",
          prompt: "Stopped after repeated actions did not make progress.",
        },
      ],
    },
  },
  {
    type: "token_budget",
    title: "Token budget",
    titleKey: "agentConfig.loopMode.tokenGateTitle",
    description: "Limit prompt and completion token usage.",
    descriptionKey: "agentConfig.loopMode.tokenGateDescription",
    icon: <Gauge size={15} />,
    defaults: { max_total_tokens: 120000 },
  },
  {
    type: "timeout",
    title: "Loop time limit",
    titleKey: "agentConfig.loopMode.timeoutGateTitle",
    description: "Stop at the next loop boundary after elapsed time.",
    descriptionKey: "agentConfig.loopMode.timeoutGateDescription",
    icon: <Clock3 size={15} />,
    defaults: { max_seconds: 1800 },
  },
  {
    type: "tool_call_budget",
    title: "Tool-call budget",
    titleKey: "agentConfig.loopMode.toolBudgetGateTitle",
    description: "Limit all calls and selected tools.",
    descriptionKey: "agentConfig.loopMode.toolBudgetGateDescription",
    icon: <Wrench size={15} />,
    defaults: { max_calls: 30, per_tool: {} },
  },
  {
    type: "qualitative_rubric",
    title: "Qualitative completion check",
    titleKey: "agentConfig.loopMode.qualitativeRubricTitle",
    description: "Check text responses without tool calls before ending.",
    descriptionKey: "agentConfig.loopMode.qualitativeRubricDescription",
    icon: <CheckCircle size={15} />,
    defaults: {
      rubric: "Every explicit user requirement must be addressed.",
      max_evaluations: 1,
    },
    exclusiveGroup: "completion_rubric",
  },
  {
    type: "completion_rubric",
    title: "Completion signal check",
    titleKey: "agentConfig.loopMode.completionRubricTitle",
    description:
      "Check text responses without tool calls for a completion signal.",
    descriptionKey: "agentConfig.loopMode.completionRubricDescription",
    icon: <ListChecks size={15} />,
    defaults: {
      prompt:
        "Treat the task as complete only when every explicit user requirement has been addressed. If any requirement remains, the task is incomplete and work must continue until it is addressed.",
      completion_signal: "COMPLETED",
      max_evaluations: 3,
    },
    exclusiveGroup: "completion_rubric",
  },
];

export function gateDefinition(type: CustomGateType) {
  return GATE_DEFINITIONS.find((item) => item.type === type)!;
}

export const TEMPLATES: Record<string, CustomGateType[]> = {
  safe: ["iteration", "token_budget", "doom_loop", "qualitative_rubric"],
  research: ["iteration", "timeout", "tool_call_budget", "doom_loop"],
  quality: ["iteration", "token_budget", "doom_loop", "completion_rubric"],
  blank: [],
};

export function makeGate(
  type: CustomGateType,
  nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
): GateInstanceConfig {
  const definition = gateDefinition(type);
  return {
    id: `${type}-${nonce}`,
    type,
    enabled: true,
    params: structuredClone(definition.defaults),
  };
}

export function buildCustomLoopMode(
  existing: CustomLoopModeConfig[],
  name: string,
  command: string,
  template: string,
  nonce = Date.now(),
  description = "A custom gate pipeline.",
): CustomLoopModeConfig {
  const baseCommand = command || "custom-mode";
  const slashCommand = uniqueValue(
    baseCommand,
    new Set(existing.map((mode) => mode.slash_command)),
    64,
  );
  const id = uniqueValue(
    baseCommand,
    new Set(existing.map((mode) => mode.id)),
    64,
  );
  return {
    id,
    name,
    slash_command: slashCommand,
    description,
    enabled: template !== "blank",
    gates: TEMPLATES[template].map((type, index) =>
      makeGate(type, `${nonce}-${index}`),
    ),
  };
}

export function uniqueValue(
  base: string,
  existing: Set<string>,
  maxLength: number,
  normalize: (value: string) => string = (value) => value,
): string {
  let candidate = base.slice(0, maxLength);
  let suffix = 2;
  while (existing.has(normalize(candidate))) {
    const suffixText = `-${suffix}`;
    candidate = `${base.slice(0, maxLength - suffixText.length)}${suffixText}`;
    suffix += 1;
  }
  return candidate;
}

export function normalizeLoopModeName(name: string | undefined): string {
  return (name || "").trim().toUpperCase().toLowerCase();
}

export function hasDuplicateLoopModeName(
  modes: CustomLoopModeConfig[],
  name: string | undefined,
  ignoredIndex = -1,
): boolean {
  const normalized = normalizeLoopModeName(name);
  if (!normalized) return false;
  return modes.some(
    (mode, index) =>
      index !== ignoredIndex && normalizeLoopModeName(mode.name) === normalized,
  );
}

export function reorderCustomGates(
  gates: GateInstanceConfig[],
  from: number,
  to: number,
): GateInstanceConfig[] {
  if (from < 0 || to < 0 || from >= gates.length || to >= gates.length) {
    return gates;
  }
  return arrayMove(gates, from, to);
}
