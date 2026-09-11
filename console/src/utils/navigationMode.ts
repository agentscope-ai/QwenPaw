interface LocationLike {
  pathname: string;
  search?: string;
  hash?: string;
}

const CONSOLE_BASENAME = "/console";
const OS_PAW_APP_STATE_KEY = "osPawAppId";

function historyStateRecord(state: unknown): Record<string, unknown> {
  if (!state || typeof state !== "object" || Array.isArray(state)) return {};
  return state as Record<string, unknown>;
}

function pathnameOnly(path: string): string {
  return path.split(/[?#]/, 1)[0] || "/";
}

export function getRouterBasename(pathname: string): string | undefined {
  return /^\/console(?:\/|$)/.test(pathname) ? CONSOLE_BASENAME : undefined;
}

export function stripRouterBasename(pathname: string): string {
  const basename = getRouterBasename(pathname);
  if (!basename) return pathname || "/";
  return pathname.slice(basename.length) || "/";
}

export function isOsPath(path: string): boolean {
  const pathname = stripRouterBasename(pathnameOnly(path));
  // Descendants still enter the shell so it can canonicalize them to /os.
  return pathname === "/os" || pathname.startsWith("/os/");
}

export function isLoginPath(pathname: string): boolean {
  return stripRouterBasename(pathname) === "/login";
}

export function getAppRelativeLocation(location: LocationLike): string {
  const pathname = stripRouterBasename(location.pathname);
  return `${pathname}${location.search ?? ""}${location.hash ?? ""}`;
}

export function getLoginPath(location: LocationLike): string {
  const redirect = encodeURIComponent(getAppRelativeLocation(location));
  return `/login?redirect=${redirect}`;
}

export function getLoginHref(location: LocationLike): string {
  const basename = getRouterBasename(location.pathname) ?? "";
  return `${basename}${getLoginPath(location)}`;
}

export function addRouterBasename(
  currentPathname: string,
  appRelativePath: string,
): string {
  const basename = getRouterBasename(currentPathname) ?? "";
  return `${basename}${appRelativePath}`;
}

export function getPostLoginHref(
  currentPathname: string,
  redirect: string,
): string | null {
  if (!isOsPath(redirect)) return null;
  return getOsRootHref(currentPathname);
}

export function getOsRootHref(currentPathname: string): string {
  return addRouterBasename(currentPathname, "/os");
}

export function getOsPawAppIdFromHistoryState(
  state: unknown,
): string | undefined {
  const appId = historyStateRecord(state)[OS_PAW_APP_STATE_KEY];
  return typeof appId === "string" && appId ? appId : undefined;
}

export function withOsPawAppHistoryState(
  state: unknown,
  appId: string | null,
): Record<string, unknown> {
  const nextState = { ...historyStateRecord(state) };
  if (appId) {
    nextState[OS_PAW_APP_STATE_KEY] = appId;
  } else {
    delete nextState[OS_PAW_APP_STATE_KEY];
  }
  return nextState;
}

/** Build the classic console entry URL while preserving an optional basename. */
export function getConsoleRootHref(currentPathname: string): string {
  return addRouterBasename(currentPathname, "/chat");
}
