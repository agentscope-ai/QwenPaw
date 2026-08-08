interface LocationLike {
  pathname: string;
  search?: string;
  hash?: string;
}

const CONSOLE_BASENAME = "/console";

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
  return addRouterBasename(currentPathname, redirect);
}

export function getOsRootHref(currentPathname: string): string {
  return addRouterBasename(currentPathname, "/os");
}

/** Build the classic console entry URL while preserving an optional basename. */
export function getConsoleRootHref(currentPathname: string): string {
  return addRouterBasename(currentPathname, "/chat");
}

export function getOsAppHref(currentPathname: string, appPath: string): string {
  const normalized = appPath.startsWith("/") ? appPath : `/${appPath}`;
  return addRouterBasename(currentPathname, `/os${normalized}`);
}
