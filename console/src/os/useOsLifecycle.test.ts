import { describe, it, expect, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { Puzzle } from "lucide-react";
import { useOsLifecycle } from "./useOsLifecycle";
import { useOsWindows } from "./osWindowStore";
import { useOsIcons } from "./osIconStore";
import { useOsRoute } from "./osRouteStore";
import { useAgentStore } from "../stores/agentStore";
import type { OsAppDef } from "./osApps";
import type { AgentSummary } from "../api/types/agents";

function appDef(routeId: string): OsAppDef {
  return {
    routeId,
    labelKey: routeId,
    fallback: routeId,
    Icon: Puzzle,
    accent: "#6366f1",
    defaultW: 800,
    defaultH: 600,
  };
}

function registryOf(...ids: string[]): Map<string, OsAppDef> {
  return new Map(ids.map((id) => [id, appDef(id)]));
}

function agent(id: string): AgentSummary {
  return {
    id,
    name: id,
    description: "",
    workspace_dir: "",
    enabled: true,
    pinned: false,
    startup_status: "running",
  };
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", {
    value: 1920,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, "innerHeight", {
    value: 1080,
    configurable: true,
    writable: true,
  });
  useOsWindows.setState({
    windows: {},
    order: [],
    activeId: null,
    zCounter: 100,
    launcherOpen: false,
    spaceId: "default",
    saved: {},
    missionControlOpen: false,
  });
  useOsIcons.setState({ positions: {} });
  useOsRoute.setState({ targets: {} });
  useAgentStore.setState({ agents: [] });
});

describe("useOsLifecycle", () => {
  it("cleans windows, icons and route targets for missing apps", () => {
    const w = useOsWindows.getState();
    w.open("core.chat");
    w.open("gone.app");
    useOsIcons.getState().setPosition("gone.app", 10, 10);
    useOsIcons.getState().setPosition("core.chat", 20, 20);
    useOsRoute.setState({
      targets: {
        "gone.app": { path: "/x", nonce: 1 },
        "core.chat": { path: "/chat", nonce: 1 },
      },
    });

    renderHook(() => useOsLifecycle(registryOf("core.chat", "a", "b")));

    expect(useOsWindows.getState().windows["gone.app"]).toBeUndefined();
    expect(useOsWindows.getState().order).toEqual(["core.chat"]);
    expect(useOsIcons.getState().positions["gone.app"]).toBeUndefined();
    expect(useOsIcons.getState().positions["core.chat"]).toBeDefined();
    expect(useOsRoute.getState().targets["gone.app"]).toBeUndefined();
    expect(useOsRoute.getState().targets["core.chat"]).toBeDefined();
  });

  it("skips cleanup while the registry only holds system apps", () => {
    useOsWindows.getState().open("gone.app");

    renderHook(() => useOsLifecycle(registryOf("os.store", "os.settings")));

    expect(useOsWindows.getState().windows["gone.app"]).toBeDefined();
  });

  it("prunes saved spaces for deleted agents once agents are loaded", () => {
    const w = useOsWindows.getState();
    w.open("core.chat");
    w.switchSpace("agent-b");
    w.switchSpace("agent-c"); // saved: default, agent-b

    useAgentStore.setState({ agents: [agent("default")] });
    renderHook(() => useOsLifecycle(registryOf("core.chat", "a", "b")));

    const saved = useOsWindows.getState().saved;
    expect(saved["default"]).toBeDefined();
    expect(saved["agent-b"]).toBeUndefined();
    // The displayed space always survives, even if absent from the list.
    expect(useOsWindows.getState().spaceId).toBe("agent-c");
  });

  it("never prunes spaces from an empty (unloaded) agent list", () => {
    const w = useOsWindows.getState();
    w.open("core.chat");
    w.switchSpace("agent-b"); // saved: default

    renderHook(() => useOsLifecycle(registryOf("core.chat", "a", "b")));

    expect(useOsWindows.getState().saved["default"]).toBeDefined();
  });
});
