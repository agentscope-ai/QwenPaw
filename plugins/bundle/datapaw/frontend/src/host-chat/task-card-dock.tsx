import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import TaskGraphPanel from "../pages/Chat/components/TaskGraphPanel";
import TaskNodeDrawer from "../pages/Chat/components/TaskGraphPanel/TaskNodeDrawer";
import type { PlanSnapshot } from "../pages/Chat/components/TaskGraphPanel/types";
import type { PlanSnapshot as UiPlanSnapshot } from "@datapaw/ui/task-graph/types";
import { resolveBackendSessionId } from "../pages/Chat/components/ChatSenderToolbar/utils";
import { PluginI18nProvider } from "./plugin-i18n";
import { isDatapawAgentSelected } from "./fetch-patch";
import { PLUGIN_ID } from "../plugin/constants";
import { tasksApi } from "../api/modules/tasks";
import {
  getDisplayPlan,
  setCurrentPlan,
  subscribeCurrentPlan,
} from "@datapaw/ui/lib/plan-store";

export const SENDER_PREFIX_ID = "datapaw-task-card-sender-prefix";

function loadCachedPlan(sessionId: string): PlanSnapshot | null {
  try {
    const raw = localStorage.getItem(`datapaw_task_card:v1:${sessionId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { plan?: PlanSnapshot };
    return parsed?.plan ?? null;
  } catch {
    return null;
  }
}

function useDatapawAgentSelected(): boolean {
  const [selected, setSelected] = useState(isDatapawAgentSelected);

  useEffect(() => {
    const tick = () => setSelected(isDatapawAgentSelected());
    tick();
    window.addEventListener("popstate", tick);
    const onStorage = () => tick();
    window.addEventListener("storage", onStorage);
    const interval = window.setInterval(tick, 800);
    return () => {
      window.removeEventListener("popstate", tick);
      window.removeEventListener("storage", onStorage);
      window.clearInterval(interval);
    };
  }, []);

  return selected;
}

/** Renders the task graph panel above the chat input (via sender.addPrefix). */
export function TaskCardDockPrefix() {
  const datapawAgent = useDatapawAgentSelected();
  const plan = useSyncExternalStore(
    subscribeCurrentPlan,
    () => getDisplayPlan() as PlanSnapshot | null,
    () => null,
  );
  const [drawerNodeId, setDrawerNodeId] = useState<string | null>(null);

  useEffect(() => {
    if (!datapawAgent) return;
    const sid = resolveBackendSessionId();
    if (!sid) return;
    const cached = loadCachedPlan(sid);
    if (cached && !getDisplayPlan()) {
      setCurrentPlan(cached as UiPlanSnapshot);
    }
  }, [datapawAgent]);

  const sessionId =
    resolveBackendSessionId() ||
    (window as Window & { currentSessionId?: string }).currentSessionId ||
    "";
  const userId =
    (window as Window & { currentUserId?: string }).currentUserId || "default";

  const drawerNode =
    drawerNodeId && plan ? plan.nodes[drawerNodeId] : null;

  const allFiles = useMemo(() => {
    if (!plan) return [];
    return Object.values(plan.nodes).flatMap((n) =>
      (n.output?.files || []).map((f) => ({
        ...f,
        _nodeName: n.name || n.node_id,
      })),
    );
  }, [plan]);

  const handlePlanCorrection = useCallback(
    async (yaml: string) => {
      if (!sessionId) return;
      await tasksApi.putSop(sessionId, userId, yaml);
      const summary = await tasksApi.getSummary(sessionId, userId);
      if (summary?.current_plan) {
        setCurrentPlan(summary.current_plan as UiPlanSnapshot);
      }
    },
    [sessionId, userId],
  );

  if (!datapawAgent || !plan) return null;

  return (
    <div
      className="datapaw-task-card-sender-prefix"
      data-datapaw-task-card-sender-prefix="true"
    >
      <TaskGraphPanel
        plan={plan}
        onNodeClick={(nodeId) => setDrawerNodeId(nodeId)}
        onPlanCorrection={handlePlanCorrection}
        showActions
      />
      {drawerNode ? (
        <TaskNodeDrawer
          node={drawerNode}
          allFiles={allFiles}
          isStreaming={drawerNode.state === "in_progress"}
          streamEvents={[]}
          sessionId={sessionId}
          userId={userId}
          onClose={() => setDrawerNodeId(null)}
        />
      ) : null}
    </div>
  );
}

export function registerTaskCardSenderPrefix(): { dispose: () => void } | void {
  const chat = (
    window as {
      QwenPaw?: {
        chat?: {
          sender?: {
            addPrefix: (
              pluginId: string,
              node: ReactNode,
              opts?: { id?: string; order?: number },
            ) => { dispose: () => void };
          };
        };
      };
    }
  ).QwenPaw?.chat;

  if (!chat?.sender?.addPrefix) {
    console.warn(
      `[${PLUGIN_ID}] window.QwenPaw.chat.sender.addPrefix missing — task card dock skipped`,
    );
    return;
  }

  const disposable = chat.sender.addPrefix(
    PLUGIN_ID,
    <PluginI18nProvider>
      <TaskCardDockPrefix />
    </PluginI18nProvider>,
    { id: SENDER_PREFIX_ID, order: 0 },
  );

  return disposable;
}
