import { useCallback, useEffect, useState } from "react";

import { loadPawApp } from "./usePluginLoader";

export type PawAppRuntimeState = "loading" | "ready" | "failed";

export interface PawAppRuntime {
  state: PawAppRuntimeState;
  retry: () => void;
}

/** Load one PawApp and expose the same lifecycle to every host surface. */
export function usePawAppRuntime(
  appId: string,
  entryPage: string,
): PawAppRuntime {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PawAppRuntimeState>("loading");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    loadPawApp(appId, entryPage)
      .then(() => {
        if (cancelled) return;
        setState("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setState("failed");
      });
    return () => {
      cancelled = true;
    };
  }, [appId, attempt, entryPage]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { state, retry };
}
