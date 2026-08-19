import { useCallback } from "react";
import { useOsWindows } from "./osWindowStore";

/** Open an app through the shared desktop launcher entry point. */
export function useOsAppLauncher(): (routeId: string) => Promise<boolean> {
  return useCallback(async (routeId: string) => {
    useOsWindows.getState().open(routeId);
    return true;
  }, []);
}
