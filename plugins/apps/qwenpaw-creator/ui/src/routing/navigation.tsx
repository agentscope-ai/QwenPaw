import {
  Link as ReactRouterLink,
  useLocation,
  useNavigate,
  useParams as useReactRouterParams,
  useSearchParams as useReactRouterSearchParams,
  type LinkProps as ReactRouterLinkProps,
  type NavigateFunction,
} from "react-router-dom";
import { useCallback, useEffect, useMemo } from "react";

let activeNavigate: NavigateFunction | null = null;

export const CREATOR_NAVIGATION_MESSAGE = "qwenpaw-creator:navigation";
export const CREATOR_RESTORE_ROUTE_MESSAGE = "qwenpaw-creator:restore-route";

export function normalizeCreatorRoute(path: unknown): string | null {
  if (
    typeof path !== "string" ||
    !path.startsWith("/") ||
    path.startsWith("//") ||
    path.includes("#")
  ) {
    return null;
  }
  const parsed = new URL(path, "http://qwenpaw-creator.local");
  return `${parsed.pathname}${parsed.search}`;
}

/**
 * Registers React Router's imperative navigator for event handlers that live
 * outside React components. Components should prefer `useRouter`.
 */
export function NavigationRuntime() {
  const routerNavigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    activeNavigate = routerNavigate;
    return () => {
      if (activeNavigate === routerNavigate) activeNavigate = null;
    };
  }, [routerNavigate]);

  useEffect(() => {
    if (window.parent === window) return;
    window.parent.postMessage(
      {
        type: CREATOR_NAVIGATION_MESSAGE,
        path: `${location.pathname}${location.search}`,
      },
      "*",
    );
  }, [location.pathname, location.search]);

  useEffect(() => {
    if (window.parent === window) return;

    const restoreRoute = (event: MessageEvent) => {
      if (
        event.source !== window.parent ||
        event.data?.type !== CREATOR_RESTORE_ROUTE_MESSAGE
      )
        return;
      const path = normalizeCreatorRoute(event.data.path);
      if (!path || path === `${location.pathname}${location.search}`) return;
      routerNavigate(path, { replace: true });
    };

    window.addEventListener("message", restoreRoute);
    return () => window.removeEventListener("message", restoreRoute);
  }, [location.pathname, location.search, routerNavigate]);

  return null;
}

function navigateByHash(path: string, replace: boolean): void {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const url = `${window.location.pathname}${window.location.search}#${normalized}`;
  window.history[replace ? "replaceState" : "pushState"](null, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** Imperative navigation for non-component utilities. */
export function navigate(path: string, replace = false): void {
  if (activeNavigate) {
    activeNavigate(path, { replace });
    return;
  }
  navigateByHash(path, replace);
}

export function usePathname(): string {
  return useLocation().pathname;
}

/** Keeps the previous read-only URLSearchParams call shape. */
export function useSearchParams(): URLSearchParams {
  const [searchParams] = useReactRouterSearchParams();
  return searchParams;
}

export function useParams(): Readonly<Record<string, string | undefined>> {
  return useReactRouterParams();
}

export function useRouter() {
  const routerNavigate = useNavigate();
  return useMemo(
    () => ({
      push: (path: string) => routerNavigate(path),
      replace: (path: string) => routerNavigate(path, { replace: true }),
      back: () => routerNavigate(-1),
    }),
    [routerNavigate],
  );
}

type LinkProps = Omit<ReactRouterLinkProps, "to"> & { href: string };

export function Link({ href, ...props }: LinkProps) {
  return <ReactRouterLink {...props} to={href} />;
}

export function useNavigateTo() {
  const routerNavigate = useNavigate();
  return useCallback(
    (path: string, replace = false) => routerNavigate(path, { replace }),
    [routerNavigate],
  );
}
