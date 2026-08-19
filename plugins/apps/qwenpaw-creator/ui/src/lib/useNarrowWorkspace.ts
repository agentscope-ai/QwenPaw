import { useEffect, useState } from "react";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";

/**
 * True when the sidebar AgentDock is open and squeezes the workspace below
 * the drawer breakpoint (720px). Pages then move their detail panel into the
 * right-rail slot under the dock (ProjectLayout's [data-detail-rail]) so the
 * dock keeps the top half and the detail gets the bottom half, instead of
 * overlaying the workspace.
 */
export function useNarrowWorkspace(): boolean {
  const open = useAgentDockUiStore((state) => state.open);
  const width = useAgentDockUiStore((state) => state.width);
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window === "undefined" ? 1920 : window.innerWidth,
  );

  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return open && viewportWidth - width < 720;
}

/** The portal target rendered by ProjectLayout; null until the rail mounts. */
export function useDetailRail(active: boolean): HTMLElement | null {
  const [rail, setRail] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!active) {
      setRail(null);
      return;
    }
    setRail(document.querySelector<HTMLElement>("[data-detail-rail]"));
  }, [active]);
  return rail;
}
