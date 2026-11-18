/** Normalize a router prefix; an empty result represents the site root. */
export function normalizeConsoleBasename(value?: string): string {
  const path = (value?.trim() || "/console").replace(/^\/+|\/+$/g, "");
  return path ? `/${path}` : "";
}
