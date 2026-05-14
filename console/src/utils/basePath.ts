export function normalizeBasePath(base = import.meta.env.BASE_URL): string {
  const raw = (base || "").trim();
  if (!raw || raw === "/") return "";
  return `/${raw.replace(/^\/+|\/+$/g, "")}`;
}

export function getRuntimeBasePath(
  pathname = typeof window !== "undefined" ? window.location.pathname : "",
  buildBase = import.meta.env.BASE_URL,
): string {
  const configured = normalizeBasePath(buildBase);
  if (configured) return configured;
  return /^\/console(?:\/|$)/.test(pathname) ? "/console" : "";
}

export function getRouterBasename(
  pathname: string,
  buildBase = import.meta.env.BASE_URL,
): string | undefined {
  return getRuntimeBasePath(pathname, buildBase) || undefined;
}

export function stripRuntimeBasePath(
  path: string,
  pathname = typeof window !== "undefined" ? window.location.pathname : "",
  buildBase = import.meta.env.BASE_URL,
): string {
  const base = getRuntimeBasePath(pathname, buildBase);
  if (!base) return path || "/";
  if (path === base) return "/";
  if (path.startsWith(`${base}/`)) return path.slice(base.length) || "/";
  return path || "/";
}

export function withRuntimeBasePath(path: string): string {
  const base = getRuntimeBasePath();
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}

export function withBuildBasePath(path: string): string {
  const base = normalizeBasePath(import.meta.env.BASE_URL);
  const normalized = path.replace(/^\/+/, "");
  return base ? `${base}/${normalized}` : `/${normalized}`;
}
