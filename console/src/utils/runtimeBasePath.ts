declare global {
  interface Window {
    __qpBase?: string;
  }
}

export function getRuntimeBasePath(): string {
  if (typeof window === "undefined") return "";
  const value = window.__qpBase?.trim() || "";
  if (!value || value === "/") return "";
  if (!value.startsWith("/") || /[?#\\]/.test(value)) return "";
  const path = value.replace(/\/+$/, "");
  try {
    const invalid = path
      .split("/")
      .slice(1)
      .some((segment) => {
        const decoded = decodeURIComponent(segment);
        return (
          !segment ||
          decoded === "." ||
          decoded === ".." ||
          decoded.includes("/") ||
          decoded.includes("\\")
        );
      });
    return invalid ? "" : path;
  } catch {
    return "";
  }
}

export function getConsoleAssetUrl(filename: string): string {
  const name = filename.replace(/^\/+/, "");
  const runtimeBasePath = getRuntimeBasePath();
  if (runtimeBasePath) return `${runtimeBasePath}/${name}`;
  const buildBase = import.meta.env.BASE_URL;
  return `${buildBase === "./" ? "/" : buildBase}${name}`;
}
