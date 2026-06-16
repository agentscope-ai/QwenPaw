import { useEffect, useState } from "react";
import { isDatapawPluginContext } from "@/api/authHeaders";

/** List route base — host chat lives at `/chat/:id`, plugin pages at `/plugin/datapaw/…`. */
export function getDataConnectionRouteBase(): string {
  return isDatapawPluginContext()
    ? "/plugin/datapaw/datapaw/data-connection"
    : "/datapaw/data-connection";
}

export function navigateDataConnection(subpath = ""): void {
  const base = getDataConnectionRouteBase();
  const path = subpath ? `${base}${subpath.startsWith("/") ? subpath : `/${subpath}`}` : base;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
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
    const sync = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  return pathname;
}
