import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { PawAppTaskResult } from "../../../api/modules/pawappTasks";

interface TaskObservation {
  callId: string;
  source: string;
  order: number;
  result: PawAppTaskResult;
}

export interface PawAppTaskSurface {
  canonicalCallId: string;
  latestStatusCallId: string | null;
  latestResult: PawAppTaskResult;
  observationCount: number;
  statusCheckCount: number;
}

interface PawAppTaskSurfaceContextValue {
  observe: (
    surfaceKey: string,
    callId: string,
    source: string,
    result: PawAppTaskResult,
  ) => void;
  scopeKey: string;
  surfaces: ReadonlyMap<string, PawAppTaskSurface>;
}

const PawAppTaskSurfaceContext =
  createContext<PawAppTaskSurfaceContextValue | null>(null);

function observationSequence(observation: TaskObservation): number {
  return observation.result.task?.event_sequence ?? -1;
}

function chooseCanonical(
  observations: readonly TaskObservation[],
): TaskObservation {
  return [...observations].sort((left, right) => {
    const leftPriority = left.source === "delegate" ? 0 : 1;
    const rightPriority = right.source === "delegate" ? 0 : 1;
    return (
      leftPriority - rightPriority ||
      observationSequence(left) - observationSequence(right) ||
      left.order - right.order
    );
  })[0];
}

function chooseLatest(
  observations: readonly TaskObservation[],
): TaskObservation {
  return [...observations].sort(
    (left, right) =>
      observationSequence(right) - observationSequence(left) ||
      right.order - left.order,
  )[0];
}

export function pawAppTaskSurfaceKey(
  result: PawAppTaskResult | null,
): string | null {
  const taskId = result?.task?.task_id;
  if (!taskId) return null;
  return `${result.app_id}:${result.workspace_id}:${taskId}`;
}

export function PawAppTaskSurfaceProvider({
  children,
  scopeKey,
}: {
  children: ReactNode;
  scopeKey?: string;
}) {
  const observations = useRef(new Map<string, Map<string, TaskObservation>>());
  const nextOrder = useRef(0);
  const [surfaces, setSurfaces] = useState(
    () => new Map<string, PawAppTaskSurface>(),
  );

  const observe = useCallback(
    (
      surfaceKey: string,
      callId: string,
      source: string,
      result: PawAppTaskResult,
    ) => {
      let taskObservations = observations.current.get(surfaceKey);
      if (!taskObservations) {
        taskObservations = new Map();
        observations.current.set(surfaceKey, taskObservations);
      }
      const previous = taskObservations.get(callId);
      if (
        previous &&
        previous.source === source &&
        previous.result === result
      ) {
        return;
      }
      taskObservations.set(callId, {
        callId,
        source,
        order: previous?.order ?? nextOrder.current++,
        result,
      });
      const values = [...taskObservations.values()];
      const canonical = chooseCanonical(values);
      const latest = chooseLatest(values);
      const statusChecks = values.filter(
        (observation) => observation.source === "get_app_task",
      );
      const nextSurface: PawAppTaskSurface = {
        canonicalCallId: canonical.callId,
        latestStatusCallId: statusChecks.length
          ? chooseLatest(statusChecks).callId
          : null,
        latestResult: latest.result,
        observationCount: values.length,
        statusCheckCount: statusChecks.length,
      };
      setSurfaces((current) => {
        const existing = current.get(surfaceKey);
        if (
          existing?.canonicalCallId === nextSurface.canonicalCallId &&
          existing.latestStatusCallId === nextSurface.latestStatusCallId &&
          existing.latestResult === nextSurface.latestResult &&
          existing.observationCount === nextSurface.observationCount &&
          existing.statusCheckCount === nextSurface.statusCheckCount
        ) {
          return current;
        }
        const next = new Map(current);
        next.set(surfaceKey, nextSurface);
        return next;
      });
    },
    [],
  );

  const value = useMemo(
    () => ({ observe, scopeKey: scopeKey ?? "default", surfaces }),
    [observe, scopeKey, surfaces],
  );
  return (
    <PawAppTaskSurfaceContext.Provider value={value}>
      {children}
    </PawAppTaskSurfaceContext.Provider>
  );
}

export function usePawAppTaskSurface(
  callId: string,
  source: string,
  result: PawAppTaskResult | null,
): {
  managed: boolean;
  ready: boolean;
  canonical: boolean;
  latestStatusCheck: boolean;
  result: PawAppTaskResult | null;
  observationCount: number;
  statusCheckCount: number;
} {
  const context = useContext(PawAppTaskSurfaceContext);
  const observe = context?.observe;
  const taskKey = pawAppTaskSurfaceKey(result);
  const surfaceKey =
    context && taskKey ? `${context.scopeKey}:${taskKey}` : taskKey;
  useEffect(() => {
    if (!observe || !surfaceKey || !result) return;
    observe(surfaceKey, callId, source, result);
  }, [callId, observe, result, source, surfaceKey]);

  if (!context || !surfaceKey) {
    return {
      managed: false,
      ready: true,
      canonical: true,
      latestStatusCheck: source === "get_app_task",
      result,
      observationCount: result?.task ? 1 : 0,
      statusCheckCount: source === "get_app_task" && result?.task ? 1 : 0,
    };
  }
  const surface = context.surfaces.get(surfaceKey);
  return {
    managed: true,
    ready: !!surface,
    canonical: surface?.canonicalCallId === callId,
    latestStatusCheck: surface?.latestStatusCallId === callId,
    result: surface?.latestResult ?? result,
    observationCount: surface?.observationCount ?? 0,
    statusCheckCount: surface?.statusCheckCount ?? 0,
  };
}
