import type { AppStatus } from "./api";
import type {
  PawDependencyHealthState,
  PawDependencySnapshot,
  PawDependencyStatus,
} from "./sdk";

export type StatusTone = "ready" | "warning" | "error" | "checking";

export interface StatusCategory {
  id: "core" | "data" | "graph" | "skills";
  label: string;
  detail: string;
  tone: StatusTone;
  optional?: boolean;
}

export interface AppStatusModel {
  label: "Ready" | "Degraded" | "Unavailable" | "Checking";
  detail: string;
  tone: StatusTone;
  checkedAt?: string;
  categories: StatusCategory[];
}

export interface DependencyGroup {
  id: "core" | "data" | "optional";
  label: string;
  description: string;
  dependencies: PawDependencyStatus[];
}

function toneForHealth(
  health: PawDependencyHealthState | undefined,
): StatusTone {
  if (health === "healthy") return "ready";
  if (health === "degraded") return "warning";
  if (health === "unavailable") return "error";
  return "checking";
}

function aggregateTone(dependencies: PawDependencyStatus[]): StatusTone {
  if (dependencies.some((item) => item.health === "unavailable")) {
    return "error";
  }
  if (dependencies.some((item) => item.health === "degraded")) {
    return "warning";
  }
  if (
    dependencies.length === 0 ||
    dependencies.some((item) => ["unknown", "checking"].includes(item.health))
  ) {
    return "checking";
  }
  return "ready";
}

export function groupDependencies(
  dependencies: PawDependencyStatus[],
): DependencyGroup[] {
  const core = dependencies.filter(
    (item) => item.required || item.id === "context",
  );
  const data = dependencies.filter((item) => item.id.startsWith("source:"));
  const claimed = new Set([...core, ...data].map((item) => item.id));
  const optional = dependencies.filter((item) => !claimed.has(item.id));
  return [
    {
      id: "core",
      label: "Core services",
      description: "Required runtime and context services",
      dependencies: core,
    },
    {
      id: "data",
      label: "Business data",
      description: "Governed query connections",
      dependencies: data,
    },
    {
      id: "optional",
      label: "Optional capabilities",
      description: "Graph and enrichment services",
      dependencies: optional,
    },
  ].filter((group) => group.dependencies.length > 0) as DependencyGroup[];
}

export function buildAppStatusModel(
  status: AppStatus | undefined,
  snapshot: PawDependencySnapshot | undefined,
  selectedSourceId = "",
): AppStatusModel {
  const dependencies = snapshot?.dependencies || [];
  const groups = groupDependencies(dependencies);
  const core = groups.find((group) => group.id === "core")?.dependencies || [];
  const sources =
    groups.find((group) => group.id === "data")?.dependencies || [];
  const graph = dependencies.find((item) => item.id === "graph-store");
  const selectedSource = selectedSourceId
    ? dependencies.find((item) => item.id === `source:${selectedSourceId}`)
    : undefined;

  const coreReady = core.filter((item) => item.health === "healthy").length;
  const sourceReady = sources.filter(
    (item) => item.health === "healthy",
  ).length;
  const coreTone =
    status?.service.ready === false ? "error" : aggregateTone(core);
  const selectedTone = selectedSource
    ? toneForHealth(selectedSource.health)
    : aggregateTone(sources);
  const skillsAvailable = status?.skills?.available ?? status?.skills_available;
  const skillCount = status?.skills?.count;

  const categories: StatusCategory[] = [
    {
      id: "core",
      label: "Core",
      detail: core.length ? `${coreReady}/${core.length} ready` : "Checking",
      tone: coreTone,
    },
    {
      id: "data",
      label: "Data",
      detail: selectedSource
        ? selectedSource.health === "healthy"
          ? "Selected source ready"
          : "Selected source unavailable"
        : sources.length
        ? `${sourceReady}/${sources.length} connections ready`
        : "No connections discovered",
      tone: selectedTone,
    },
    {
      id: "graph",
      label: "Graph",
      detail: graph
        ? graph.health === "healthy"
          ? "Grounding ready"
          : "Optional unavailable"
        : "Not configured",
      tone: graph ? toneForHealth(graph.health) : "checking",
      optional: true,
    },
    {
      id: "skills",
      label: "Skills",
      detail: skillsAvailable
        ? typeof skillCount === "number"
          ? `${skillCount} loaded`
          : "Loaded"
        : "Not configured",
      tone: skillsAvailable ? "ready" : "warning",
    },
  ];

  let tone: StatusTone = "ready";
  if (coreTone === "error") tone = "error";
  else if (coreTone === "checking") tone = "checking";
  else if (selectedSource && selectedTone !== "ready") tone = "warning";
  else if (!skillsAvailable) tone = "warning";

  const label =
    tone === "ready"
      ? "Ready"
      : tone === "warning"
      ? "Degraded"
      : tone === "error"
      ? "Unavailable"
      : "Checking";
  const checkedAt = dependencies
    .map((item) => item.last_checked_at)
    .filter(Boolean)
    .sort()
    .at(-1);

  return {
    label,
    tone,
    detail: core.length
      ? `${coreReady}/${core.length} required services ready`
      : status?.service.ready
      ? "Discovering dependencies"
      : "Context service unavailable",
    checkedAt,
    categories,
  };
}
