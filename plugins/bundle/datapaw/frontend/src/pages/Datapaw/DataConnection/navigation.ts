import { useEffect, useState } from "react";
import { isDatapawPluginContext } from "@/api/authHeaders";

const DATAPAW_LOCATION_CHANGE_EVENT = "datapaw:locationchange";
const HISTORY_PATCH_MARKER = "__datapawHistoryPatch";

function dispatchDatapawLocationChange(): void {
  window.dispatchEvent(new Event(DATAPAW_LOCATION_CHANGE_EVENT));
}

function installHistoryPatch(): void {
  const historyWithMarker = window.history as History & Record<string, unknown>;
  if (historyWithMarker[HISTORY_PATCH_MARKER]) return;

  const nativePushState = window.history.pushState;
  const nativeReplaceState = window.history.replaceState;

  window.history.pushState = function pushState(...args) {
    const result = nativePushState.apply(this, args);
    dispatchDatapawLocationChange();
    return result;
  };

  window.history.replaceState = function replaceState(...args) {
    const result = nativeReplaceState.apply(this, args);
    dispatchDatapawLocationChange();
    return result;
  };

  historyWithMarker[HISTORY_PATCH_MARKER] = true;
}

/** List route base — host chat lives at `/chat/:id`, plugin pages at `/plugin/datapaw/…`. */
export function getDataConnectionRouteBase(): string {
  return isDatapawPluginContext()
    ? "/plugin/datapaw/datapaw/data-connection"
    : "/datapaw/data-connection";
}

export function navigateDataConnection(subpath = ""): void {
  const base = getDataConnectionRouteBase();
  const path = subpath
    ? `${base}${subpath.startsWith("/") ? subpath : `/${subpath}`}`
    : base;
  window.history.pushState({}, "", path);
  dispatchDatapawLocationChange();
}

export function isDataConnectionListPath(pathname: string): boolean {
  return (
    pathname === "/datapaw/data-connection" ||
    pathname === "/plugin/datapaw/datapaw/data-connection"
  );
}

/** Sync pathname when host navigation uses pushState instead of React Router. */
export function useDataConnectionPathname(): string {
  const [pathname, setPathname] = useState(() => window.location.pathname);

  useEffect(() => {
    installHistoryPatch();
    const sync = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", sync);
    window.addEventListener(DATAPAW_LOCATION_CHANGE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener(DATAPAW_LOCATION_CHANGE_EVENT, sync);
    };
  }, []);

  return pathname;
}
