import { useEffect, useState } from "react";
import type {
  PawHandoffRequest,
  PawSdk,
} from "../../../../../console/src/plugins/pawapp-sdk/types";
import { EmbeddedDataConsole } from "./EmbeddedDataConsole";

export function dataRouteFromHandoff(handoff: PawHandoffRequest): string {
  const project = handoff.context.project_ref;
  if (
    handoff.target_app_id !== "qwenpaw-data" ||
    project.app_id !== "qwenpaw-data" ||
    project.kind !== "analysis-session"
  ) {
    throw new Error("unsupported_data_handoff");
  }
  return `/console?session_id=${encodeURIComponent(project.project_id)}`;
}

/**
 * The embedded engine console owns the entire app surface: navigation,
 * branding, language, model setup (Agent Configuration), channels, and
 * the DataBridge service configuration. The shell only mounts it.
 */
export function App({ paw }: { paw: PawSdk }) {
  const handoffId = new URLSearchParams(window.location.search).get("handoff");
  const [route, setRoute] = useState<string | null>(
    handoffId ? null : "/console",
  );
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!handoffId) return;
    let active = true;
    void paw.apps
      .resolveHandoff(handoffId)
      .then((handoff) => {
        if (active) setRoute(dataRouteFromHandoff(handoff));
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [handoffId, paw]);

  return (
    <div className="qwenpaw-data-app">
      <main className="qwenpaw-data-main">
        {route && <EmbeddedDataConsole route={route} active />}
        {!route && !error && (
          <p className="qwenpaw-data-handoff">Opening analysis…</p>
        )}
        {error && (
          <p className="qwenpaw-data-handoff" role="alert">
            This analysis link is unavailable.
          </p>
        )}
      </main>
    </div>
  );
}
