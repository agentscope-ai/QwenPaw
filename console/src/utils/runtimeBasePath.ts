export function getRuntimeBasePath(): string {
  // The server injects this token; <base href> may be only the Vite build base.
  if (typeof document === "undefined") return "";
  const path = document.head
    ?.querySelector('meta[name="qwenpaw-base-path"]')
    ?.getAttribute("content");
  if (path === "") return "";
  if (
    typeof path !== "string" ||
    !path.startsWith("/") ||
    path.endsWith("/") ||
    /[%?#\\]/.test(path) ||
    [...path].some((character) => {
      const code = character.codePointAt(0) ?? 0;
      return code <= 0x1f || (code >= 0x7f && code <= 0x9f);
    })
  ) {
    return "";
  }
  const invalid = path
    .split("/")
    .slice(1)
    .some((segment) => !segment || segment === "." || segment === "..");
  return invalid ? "" : path;
}

export function getConsoleAssetUrl(filename: string): string {
  const name = filename.replace(/^\/+/, "");
  const runtimeBasePath = getRuntimeBasePath();
  if (runtimeBasePath) return `${runtimeBasePath}/${name}`;
  const buildBase = import.meta.env.BASE_URL;
  return `${buildBase === "./" ? "/" : buildBase}${name}`;
}
