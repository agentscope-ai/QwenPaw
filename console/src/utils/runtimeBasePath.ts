export function getRuntimeBasePath(): string {
  if (typeof document === "undefined") return "";
  // Read the server's raw directory path, not the browser's normalized URL.
  const href = document.head?.querySelector("base[href]")?.getAttribute("href");
  if (
    !href?.startsWith("/") ||
    !href.endsWith("/") ||
    /[%?#\\\t\n\r]/.test(href)
  ) {
    return "";
  }
  const path = href.slice(0, -1);
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
