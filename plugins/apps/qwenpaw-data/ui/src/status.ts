import type { AppStatus } from "./api";
import type {
  PawDependencyHealthState,
  PawDependencySnapshot,
  PawDependencyStatus,
} from "./sdk";
import { translate, type Language } from "./strings";

export type StatusTone = "ready" | "warning" | "error" | "checking";

export interface StatusCategory {
  id: "core" | "data" | "graph" | "skills";
  label: string;
  detail: string;
  tone: StatusTone;
  optional?: boolean;
}

export interface AppStatusModel {
  label: string;
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
  language: Language = "en",
): AppStatusModel {
  const t = (key: Parameters<typeof translate>[1], params?: object) =>
    translate(language, key, params as Record<string, string | number>);
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
      label: t("status.category.core"),
      detail: core.length
        ? t("status.detail.ready", { ready: coreReady, total: core.length })
        : t("status.detail.checking"),
      tone: coreTone,
    },
    {
      id: "data",
      label: t("status.category.data"),
      detail: selectedSource
        ? selectedSource.health === "healthy"
          ? t("status.detail.sourceReady")
          : t("status.detail.sourceUnavailable")
        : sources.length
        ? t("status.detail.sourcesReady", {
            ready: sourceReady,
            total: sources.length,
          })
        : t("status.detail.noSources"),
      tone: selectedTone,
    },
    {
      id: "graph",
      label: t("status.category.graph"),
      detail: graph
        ? graph.health === "healthy"
          ? t("status.detail.groundingReady")
          : t("status.detail.optionalUnavailable")
        : t("status.detail.notConfigured"),
      tone: graph ? toneForHealth(graph.health) : "checking",
      optional: true,
    },
    {
      id: "skills",
      label: t("status.category.skills"),
      detail: skillsAvailable
        ? typeof skillCount === "number"
          ? t("status.detail.skillsLoaded", { count: skillCount })
          : t("status.detail.loaded")
        : t("status.detail.notConfigured"),
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
      ? t("status.label.ready")
      : tone === "warning"
      ? t("status.label.degraded")
      : tone === "error"
      ? t("status.label.unavailable")
      : t("status.label.checking");
  const checkedAt = dependencies
    .map((item) => item.last_checked_at)
    .filter(Boolean)
    .sort()
    .at(-1);

  // The fraction only earns its place when it disagrees with the headline;
  // when every required service is up the category rows already cover it.
  return {
    label,
    tone,
    detail: core.length
      ? coreReady < core.length
        ? t("status.detail.requiredReady", {
            ready: coreReady,
            total: core.length,
          })
        : ""
      : status?.service.ready
      ? t("status.detail.discovering")
      : t("status.detail.contextUnavailable"),
    checkedAt,
    categories,
  };
}
