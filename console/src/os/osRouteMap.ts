/**
 * osRouteMap.ts — Route id <-> path helpers for the Desktop OS.
 *
 * Each OS window runs its own MemoryRouter seeded at an app "base" path (the
 * registry route path minus any splat). When a shared page component navigates
 * to a path that belongs to a DIFFERENT app, the window bridge maps that path
 * back to a route id so the OS can open/focus the correct window instead of
 * breaking out of the desktop. Pure functions — safe to call in render.
 */

/** Route id of the aggregate System Settings window. */
export const SETTINGS_APP_ID = "os.settings";

/** Minimal route shape needed here (matches ResolvedRoute from the registry). */
export interface RouteLike {
  id: string;
  path: string;
  source?: string;
}

/**
 * Settings routes surfaced inside the System Settings window (mirrors
 * SETTINGS_ITEMS in SettingsApp.tsx). Cross-app navigation to any of these
 * opens System Settings and selects the matching pane.
 */
export const SETTINGS_ROUTE_IDS = new Set<string>([
  "core.agents",
  "core.models",
  "core.skill-pool",
  "core.environments",
  "core.security",
  "core.token-usage",
  "core.backups",
  "core.voice-transcription",
  "core.debug",
]);

/**
 * Turn a registry route path into the router base for a window.
 * "/chat/*" -> "/chat", "/models" -> "/models". Falls back to "/".
 */
export function baseFromRoutePath(path: string | undefined): string {
  if (!path) return "/";
  const clean = path.replace(/\/\*$/, "").replace(/\/:.*$/, "");
  return clean || "/";
}

/** First path segment, e.g. "/chat/abc" -> "chat", "/models?x=1" -> "models". */
export function topSegment(pathname: string): string {
  const noQuery = pathname.split("?")[0];
  return noQuery.replace(/^\/+/, "").split("/")[0] || "";
}

function normalizePath(path: string): string {
  const clean = path.split(/[?#]/, 1)[0].replace(/\/+$/, "");
  return clean || "/";
}

function routeMatchScore(pathname: string, routePath: string): number {
  const path = normalizePath(pathname);
  const pattern = normalizePath(routePath);
  const pathParts = path.split("/").filter(Boolean);
  const patternParts = pattern.split("/").filter(Boolean);
  let score = 0;

  if (patternParts.length === 0) {
    return pathParts.length === 0 ? 1000 : -1;
  }

  for (let index = 0; index < patternParts.length; index += 1) {
    const part = patternParts[index];
    if (part === "*") return score + 1;
    const current = pathParts[index];
    if (!current) return -1;
    if (part.startsWith(":")) {
      score += 2;
    } else if (part === current) {
      score += part.length + 4;
    } else {
      return -1;
    }
  }

  if (pathParts.length === patternParts.length) return score + 1000;
  return score;
}

function bundleRouteId(route: RouteLike, routes: RouteLike[]): string {
  if (route.source === undefined || route.source === "core") return route.id;
  return (
    routes.find(
      (candidate) =>
        candidate.source === route.source &&
        candidate.path.startsWith("/apps/"),
    )?.id ?? route.id
  );
}

/**
 * Resolve a navigation target pathname to the most specific registered app.
 * Static paths beat parameterized parents, so `/apps/office` maps to the
 * Office PawApp instead of the aggregate `/apps/:appId` route. Every route
 * contributed by the same PawApp source maps back to its bundle window.
 */
export function pathToRouteId(
  pathname: string,
  routes: RouteLike[],
): string | undefined {
  if (normalizePath(pathname) === "/") return undefined;
  let best: RouteLike | undefined;
  let bestScore = -1;
  for (const r of routes) {
    const score = routeMatchScore(pathname, r.path);
    if (score > bestScore) {
      best = r;
      bestScore = score;
    }
  }
  return best ? bundleRouteId(best, routes) : undefined;
}
