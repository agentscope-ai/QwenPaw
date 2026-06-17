import { useCallback, useState } from "react";
import {
  tasksApi,
  type HistoricalPlanSummary,
  type TaskArtifact,
  type TasksSummaryResponse,
} from "../../../api/modules/tasks";
import { normalizeArtifactFile } from "../components/TaskGraphPanel/fileUtils";

export interface ArtifactGraphGroup {
  graphId: string;
  name: string;
  state?: string;
  isCurrent: boolean;
  fileCount: number;
}

export interface UseArtifactManageOptions {
  sessionId: string | null;
  userId: string;
  enabled?: boolean;
}

function getGraphOrderingKey(
  graphId: string,
  summary: TasksSummaryResponse | null,
  allFiles: TaskArtifact[],
): number {
  if (summary?.current_plan?.id === graphId && summary.current_plan.created_at) {
    return Date.parse(summary.current_plan.created_at) || Number.MAX_SAFE_INTEGER;
  }

  const historical = summary?.historical_plans?.find((plan) => plan.id === graphId);
  if (historical?.finished_at) {
    return Date.parse(historical.finished_at) || 0;
  }

  const graphFileTimes = allFiles
    .filter((file) => file.graph_id === graphId && file.created_at)
    .map((file) => Date.parse(file.created_at as string))
    .filter((time) => Number.isFinite(time) && time > 0);

  return graphFileTimes.length ? Math.min(...graphFileTimes) : 0;
}

function sortArtifactFilesChronologically(files: TaskArtifact[]): TaskArtifact[] {
  return [...files].sort((a, b) => {
    const at = a.created_at ? Date.parse(a.created_at) : 0;
    const bt = b.created_at ? Date.parse(b.created_at) : 0;
    if (at !== bt) return at - bt;
    return a.path.localeCompare(b.path);
  });
}

function buildGraphGroups(
  summary: TasksSummaryResponse | null,
  allFiles: TaskArtifact[],
): ArtifactGraphGroup[] {
  const metaById = new Map<
    string,
    { name: string; state?: string; isCurrent: boolean }
  >();

  if (summary?.current_plan?.id) {
    metaById.set(summary.current_plan.id, {
      name: summary.current_plan.name || summary.current_plan.id,
      state: summary.current_plan.state,
      isCurrent: true,
    });
  }

  for (const historical of summary?.historical_plans ?? []) {
    if (!historical.id || metaById.has(historical.id)) continue;
    metaById.set(historical.id, {
      name: historical.name || historical.id,
      state: historical.state,
      isCurrent: false,
    });
  }

  const countByGraph = new Map<string, number>();
  for (const file of allFiles) {
    if (!file.graph_id) continue;
    countByGraph.set(file.graph_id, (countByGraph.get(file.graph_id) ?? 0) + 1);
  }

  const graphIds = new Set([...countByGraph.keys(), ...metaById.keys()]);
  return [...graphIds]
    .map((graphId) => {
      const meta = metaById.get(graphId);
      return {
        graphId,
        name: meta?.name ?? graphId,
        state: meta?.state,
        isCurrent: meta?.isCurrent ?? false,
        fileCount: countByGraph.get(graphId) ?? 0,
      };
    })
    .sort(
      (a, b) =>
        getGraphOrderingKey(a.graphId, summary, allFiles) -
        getGraphOrderingKey(b.graphId, summary, allFiles),
    );
}

function enrichFilesWithNodeNames(
  files: TaskArtifact[],
  summary: TasksSummaryResponse | null,
): TaskArtifact[] {
  const nodeNameByGraph = new Map<string, Map<string, string>>();

  const registerPlanNodes = (graphId: string, nodes?: Record<string, { name?: string; node_id?: string }>) => {
    if (!nodes) return;
    const nodeMap = nodeNameByGraph.get(graphId) ?? new Map<string, string>();
    for (const node of Object.values(nodes)) {
      if (!node.node_id) continue;
      nodeMap.set(node.node_id, node.name || node.node_id);
    }
    nodeNameByGraph.set(graphId, nodeMap);
  };

  if (summary?.current_plan?.id) {
    registerPlanNodes(summary.current_plan.id, summary.current_plan.nodes);
  }

  return files.map((file) => {
    const normalized = normalizeArtifactFile(file);
    const nodeName = nodeNameByGraph.get(normalized.graph_id)?.get(normalized.node_id);
    if (!nodeName) return normalized;
    return { ...normalized, _nodeName: nodeName } as TaskArtifact & { _nodeName?: string };
  });
}

export function useArtifactManage({
  sessionId,
  userId,
  enabled = true,
}: UseArtifactManageOptions) {
  const [groups, setGroups] = useState<ArtifactGraphGroup[]>([]);
  const [filesByGraph, setFilesByGraph] = useState<Record<string, TaskArtifact[]>>({});
  const [loadingGraphIds, setLoadingGraphIds] = useState<Set<string>>(new Set());
  const [indexLoading, setIndexLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<TasksSummaryResponse | null>(null);

  const refreshIndex = useCallback(async (): Promise<{
    groups: ArtifactGraphGroup[];
    summary: TasksSummaryResponse | null;
  }> => {
    if (!sessionId) {
      setGroups([]);
      setSummary(null);
      return { groups: [], summary: null };
    }
    setIndexLoading(true);
    setError(null);
    try {
      const [nextSummary, filesRes] = await Promise.all([
        tasksApi.getSummary(sessionId, userId),
        tasksApi.listFiles(sessionId, userId),
      ]);
      const allFiles = filesRes.files ?? [];
      const nextGroups = buildGraphGroups(nextSummary, allFiles);
      setSummary(nextSummary);
      setGroups(nextGroups);
      return { groups: nextGroups, summary: nextSummary };
    } catch (e) {
      setGroups([]);
      setSummary(null);
      setError(e instanceof Error ? e.message : "Failed to load artifacts");
      return { groups: [], summary: null };
    } finally {
      setIndexLoading(false);
    }
  }, [sessionId, userId]);

  const loadGraphFiles = useCallback(
    async (
      graphId: string,
      opts: {
        force?: boolean;
        summary?: TasksSummaryResponse | null;
      } = {},
    ) => {
      if (!sessionId || !enabled) return;
      if (!opts.force && filesByGraph[graphId]) return;

      setLoadingGraphIds((prev) => new Set(prev).add(graphId));
      try {
        const res = await tasksApi.listFiles(sessionId, userId, {
          graph_id: graphId,
        });
        const summaryForEnrich = opts.summary ?? summary;
        const files = sortArtifactFilesChronologically(
          enrichFilesWithNodeNames(res.files ?? [], summaryForEnrich),
        );
        setFilesByGraph((prev) => ({ ...prev, [graphId]: files }));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load graph files");
      } finally {
        setLoadingGraphIds((prev) => {
          const next = new Set(prev);
          next.delete(graphId);
          return next;
        });
      }
    },
    [enabled, filesByGraph, sessionId, summary, userId],
  );

  const resetLoadedFiles = useCallback(() => {
    setFilesByGraph({});
  }, []);

  return {
    groups,
    filesByGraph,
    loadingGraphIds,
    indexLoading,
    error,
    refreshIndex,
    loadGraphFiles,
    resetLoadedFiles,
  };
}

export type { HistoricalPlanSummary };
