import { matchRoutes } from "react-router-dom";

interface SelectableRoute {
  id: string;
  path: string;
}

/** Select the same highest-priority route that React Router will render. */
export function pickSelectedKey(
  currentPath: string,
  routes: readonly SelectableRoute[],
): string {
  const matches = matchRoutes(
    routes.map((route) => ({ id: route.id, path: route.path })),
    currentPath,
  );
  return matches?.[matches.length - 1]?.route.id ?? "core.chat";
}
