import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  tasksApi,
  type DagRuntimeSnapshot,
  type HistoricalPlanSummary,
  type TaskArtifact,
} from "../../../api/modules/tasks";
import type { PlanSnapshot } from "../components/TaskGraphPanel/types";
import { parseErrorDetail } from "../../../utils/error";

function getErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback;
  const detail = parseErrorDetail(error);
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail.detail === "string") return detail.detail;
  const idx = error.message.indexOf(" - ");
  if (idx > 0) return error.message.slice(0, idx);
  return error.message || fallback;
}

function isAgentRunningError(error: unknown): boolean {
  const msg = getErrorMessage(error, "").toLowerCase();
  return msg.includes("agent is running") || msg.includes("409");
}

export interface UseTaskPanelOptions {
  sessionId: string | null;
  userId: string;
  enabled: boolean;
  /** DAG snapshot 中的 current_plan 变更（唯一数据源） */
  onPlanChange: (plan: PlanSnapshot | null) => void;
  onArtifactsChange?: (artifacts: TaskArtifact[]) => void;
}

export function useTaskPanel({
  sessionId,
  userId,
  enabled,
  onPlanChange,
  onArtifactsChange,
}: UseTaskPanelOptions) {
  const [historicalPlans, setHistoricalPlans] = useState<HistoricalPlanSummary[]>([]);
  const [artifacts, setArtifacts] = useState<TaskArtifact[]>([]);
  const [planDetailYaml, setPlanDetailYaml] = useState<string | null>(null);
  const [planDetailLoading, setPlanDetailLoading] = useState(false);
  const onPlanChangeRef = useRef(onPlanChange);
  const onArtifactsChangeRef = useRef(onArtifactsChange);

  useEffect(() => {
    onPlanChangeRef.current = onPlanChange;
  }, [onPlanChange]);

  useEffect(() => {
    onArtifactsChangeRef.current = onArtifactsChange;
  }, [onArtifactsChange]);

  const applySnapshot = useCallback((snapshot: DagRuntimeSnapshot) => {
    const plan = snapshot.current_plan ?? null;
    const nextArtifacts = snapshot.artifacts ?? [];
    setArtifacts(nextArtifacts);
    onArtifactsChangeRef.current?.(nextArtifacts);
    onPlanChangeRef.current(plan);
  }, []);

  const refreshSummary = useCallback(async (
    overrideSessionId?: string | null,
  ): Promise<PlanSnapshot | null> => {
    const sid = overrideSessionId ?? sessionId;
    if (!sid) return null;
    try {
      const summary = await tasksApi.getSummary(sid, userId);
      setHistoricalPlans(summary.historical_plans ?? []);
      const plan = summary.current_plan ?? null;
      applySnapshot({
        current_plan: plan,
        artifacts: [],
      });
      if (plan?.id) {
        const files = await tasksApi.listFiles(sid, userId, {
          graph_id: plan.id,
        });
        const listed = files.files ?? [];
        setArtifacts(listed);
        onArtifactsChangeRef.current?.(listed);
      }
      return plan;
    } catch (error) {
      console.warn("[TaskPanel] refresh summary failed:", error);
      return null;
    }
  }, [applySnapshot, sessionId, userId]);

  useEffect(() => {
    if (!enabled || !sessionId) {
      setHistoricalPlans([]);
      setArtifacts([]);
      onPlanChangeRef.current(null);
      onArtifactsChangeRef.current?.([]);
      return;
    }

    let cancelled = false;
    const abort = new AbortController();

    const bootstrap = async () => {
      await refreshSummary();
      if (cancelled) return;

      try {
        await tasksApi.subscribeDagEvents(
          sessionId,
          userId,
          (snapshot) => {
            if (!cancelled) applySnapshot(snapshot);
          },
          abort.signal,
        );
      } catch (error) {
        if (cancelled || abort.signal.aborted) return;
        console.warn("[TaskPanel] DAG SSE unavailable:", error);
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, [applySnapshot, enabled, refreshSummary, sessionId, userId]);

  const handlePlanCorrection = useCallback(
    async (yaml: string) => {
      if (!sessionId) return { ok: false as const, error: "no_session" };
      try {
        const result = await tasksApi.putSop(sessionId, userId, yaml);
        await refreshSummary();
        return { ok: true as const, detail: result.detail };
      } catch (error) {
        return {
          ok: false as const,
          error: getErrorMessage(error, "Failed to update plan"),
          agentRunning: isAgentRunningError(error),
        };
      }
    },
    [refreshSummary, sessionId, userId],
  );

  const handleDownloadSop = useCallback(async () => {
    if (!sessionId) return;
    const { blob, filename } = await tasksApi.downloadActiveSop(sessionId, userId);
    tasksApi.downloadBlob(blob, filename);
  }, [sessionId, userId]);

  const handleDownloadDag = useCallback(async () => {
    if (!sessionId) return;
    const { blob, filename } = await tasksApi.downloadActiveDag(sessionId, userId, true);
    tasksApi.downloadBlob(blob, filename);
  }, [sessionId, userId]);

  const openPlanDetail = useCallback(async () => {
    if (!sessionId) return;
    setPlanDetailLoading(true);
    try {
      const yaml = await tasksApi.fetchActiveDagYamlText(sessionId, userId, false);
      setPlanDetailYaml(yaml);
    } finally {
      setPlanDetailLoading(false);
    }
  }, [sessionId, userId]);

  const closePlanDetail = useCallback(() => {
    setPlanDetailYaml(null);
  }, []);

  return useMemo(
    () => ({
      historicalPlans,
      artifacts,
      planDetailYaml,
      planDetailLoading,
      handlePlanCorrection,
      handleDownloadSop,
      handleDownloadDag,
      openPlanDetail,
      closePlanDetail,
      refreshSummary,
    }),
    [
      artifacts,
      handleDownloadDag,
      handleDownloadSop,
      handlePlanCorrection,
      historicalPlans,
      openPlanDetail,
      closePlanDetail,
      planDetailLoading,
      planDetailYaml,
      refreshSummary,
    ],
  );
}
