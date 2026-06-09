import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import TaskGraphPanel from "../pages/Chat/components/TaskGraphPanel";
import TaskNodeDrawer from "../pages/Chat/components/TaskGraphPanel/TaskNodeDrawer";
import type {
  PlanSnapshot,
  StreamEvent,
  TaskStatusEvent,
} from "../pages/Chat/components/TaskGraphPanel/types";
import { patchHostSessionApi } from "../hostSessionApiPatch";
import { PluginI18nProvider } from "./plugin-i18n";
import { setTaskStatusHandler } from "./fetch-patch";

const INLINE_SLOT_ID = "datapaw-inline-task-graph";
const DATAPAW_AGENT_ID = "datapaw";
const STORAGE_KEY = "qwenpaw-agent-storage";

function isChatPage(): boolean {
  const path = window.location.pathname;
  return path === "/" || path.startsWith("/chat");
}

function isDatapawAgentSelected(): boolean {
  try {
    const sessionRaw = sessionStorage.getItem(STORAGE_KEY);
    if (sessionRaw) {
      const agent = JSON.parse(sessionRaw)?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent === DATAPAW_AGENT_ID;
    }
    const localRaw = localStorage.getItem(STORAGE_KEY);
    if (localRaw) {
      const agent = JSON.parse(localRaw)?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent === DATAPAW_AGENT_ID;
    }
  } catch {
    /* ignore */
  }
  return false;
}

/** Bubble list inside host AgentScopeRuntimeWebUI — same scroll area as messages. */
function findMessageListAnchor(): HTMLElement | null {
  const selectors = [
    ".qwenpaw-chat-anywhere-message-list .qwenpaw-bubble-list",
    '[class*="chat-anywhere-message-list"] [class*="bubble-list"]',
    ".qwenpaw-bubble-list",
    '[class*="bubble-list"]',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el instanceof HTMLElement) return el;
  }
  return null;
}

function removeInlineSlot(): void {
  document.getElementById(INLINE_SLOT_ID)?.remove();
}

function ensureInlineSlot(): HTMLElement | null {
  const anchor = findMessageListAnchor();
  if (!anchor) return null;

  let slot = document.getElementById(INLINE_SLOT_ID);
  if (!slot) {
    slot = document.createElement("div");
    slot.id = INLINE_SLOT_ID;
    slot.setAttribute("data-datapaw-inline-task-graph", "true");
    slot.style.cssText = [
      "width: 100%",
      "max-width: 720px",
      "margin: 16px auto",
      "padding: 0 12px",
      "box-sizing: border-box",
    ].join("; ");
    anchor.appendChild(slot);
  }
  return slot;
}

function TaskGraphInlineHost() {
  const [currentPlan, setCurrentPlan] = useState<PlanSnapshot | null>(null);
  const [drawerNodeId, setDrawerNodeId] = useState<string | null>(null);
  const [nodeStreamEventsMap, setNodeStreamEventsMap] = useState<
    Record<string, StreamEvent[]>
  >({});
  const [onChatPage, setOnChatPage] = useState(isChatPage);
  const [datapawAgent, setDatapawAgent] = useState(isDatapawAgentSelected);

  const activePlanIdRef = useRef<string | null>(null);
  const nodeStreamEventsMapRef = useRef<Record<string, StreamEvent[]>>({});
  const inlineRootRef = useRef<Root | null>(null);
  const handleNodeClickRef = useRef<(nodeId: string) => void>(() => {});

  useEffect(() => {
    const tick = () => {
      setOnChatPage(isChatPage());
      setDatapawAgent(isDatapawAgentSelected());
    };
    tick();
    window.addEventListener("popstate", tick);
    const interval = window.setInterval(tick, 800);
    return () => {
      window.removeEventListener("popstate", tick);
      window.clearInterval(interval);
    };
  }, []);

  const getAllFilesFromPlan = useMemo(() => {
    if (!currentPlan) return [];
    return Object.values(currentPlan.nodes).flatMap((n) =>
      (n.output?.files || []).map((f) => ({
        ...f,
        _nodeName: n.name || n.node_id,
      })),
    );
  }, [currentPlan]);

  const syncInlinePanel = useCallback((plan: PlanSnapshot | null) => {
    if (!plan) {
      inlineRootRef.current?.unmount();
      inlineRootRef.current = null;
      removeInlineSlot();
      return;
    }

    const slot = ensureInlineSlot();
    if (!slot) return;

    const panel = (
      <TaskGraphPanel
        plan={plan}
        onNodeClick={(nodeId) => handleNodeClickRef.current(nodeId)}
      />
    );

    if (!inlineRootRef.current) {
      inlineRootRef.current = createRoot(slot);
    }
    inlineRootRef.current.render(panel);
  }, []);

  const handleTaskStatusEvent = useCallback(
    (event: TaskStatusEvent) => {
      const planData = event.graph_snapshot ?? event.plan;

      switch (event.event_type) {
        case "graph_created":
        case "graph_updated":
          if (planData) {
            if (
              activePlanIdRef.current &&
              activePlanIdRef.current !== planData.id
            ) {
              setCurrentPlan(null);
              syncInlinePanel(null);
            }
            activePlanIdRef.current = planData.id;
            setCurrentPlan(planData);
            nodeStreamEventsMapRef.current = {};
            setNodeStreamEventsMap({});
            syncInlinePanel(planData);
          }
          break;
        case "graph_finished":
          if (planData) {
            setCurrentPlan(planData);
            syncInlinePanel(planData);
          }
          break;
        case "graph_archived":
          activePlanIdRef.current = null;
          setCurrentPlan(null);
          nodeStreamEventsMapRef.current = {};
          setNodeStreamEventsMap({});
          syncInlinePanel(null);
          break;
        default:
          break;
      }
    },
    [syncInlinePanel],
  );

  useEffect(() => {
    setTaskStatusHandler(handleTaskStatusEvent);
    return () => setTaskStatusHandler(null);
  }, [handleTaskStatusEvent]);

  useEffect(() => {
    if (!onChatPage || !datapawAgent) {
      setCurrentPlan(null);
      syncInlinePanel(null);
    }
  }, [onChatPage, datapawAgent, syncInlinePanel]);

  useEffect(() => {
    if (currentPlan && onChatPage && datapawAgent) {
      syncInlinePanel(currentPlan);
    }
  }, [currentPlan, onChatPage, datapawAgent, syncInlinePanel]);

  useEffect(
    () => () => {
      inlineRootRef.current?.unmount();
      inlineRootRef.current = null;
      removeInlineSlot();
    },
    [],
  );

  const handleNodeClick = useCallback((nodeId: string) => {
    setDrawerNodeId(nodeId);
  }, []);
  handleNodeClickRef.current = handleNodeClick;

  if (!onChatPage || !datapawAgent || !currentPlan) {
    return null;
  }

  const drawerNode =
    drawerNodeId && currentPlan.nodes[drawerNodeId]
      ? currentPlan.nodes[drawerNodeId]
      : null;

  return drawerNode ? (
    <TaskNodeDrawer
      node={drawerNode}
      allFiles={getAllFilesFromPlan}
      isStreaming={drawerNode.state === "in_progress"}
      streamEvents={nodeStreamEventsMap[drawerNodeId!] || []}
      sessionId={
        (window as Window & { currentSessionId?: string }).currentSessionId ||
        ""
      }
      userId={
        (window as Window & { currentUserId?: string }).currentUserId ||
        "default"
      }
      onClose={() => setDrawerNodeId(null)}
    />
  ) : null;
}

let hostRoot: Root | null = null;

export function mountTaskPanel(): void {
  patchHostSessionApi();

  if (hostRoot) return;

  const host = document.createElement("div");
  host.id = "datapaw-task-graph-host";
  host.style.display = "contents";
  document.body.appendChild(host);

  hostRoot = createRoot(host);
  hostRoot.render(
    <PluginI18nProvider>
      <TaskGraphInlineHost />
    </PluginI18nProvider>,
  );

  console.info("[datapaw] Task graph inline mount (chat message list)");
}
