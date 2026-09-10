export function isPlatformGatewayAuthResponse(
  status: number,
  contentType: string | null,
): boolean {
  return (status === 401 || status === 403) &&
    Boolean(contentType?.toLowerCase().includes("text/html"));
}

export function platformAccessPath(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^https?:\/\//i.test(trimmed)) {
    try {
      const url = new URL(trimmed);
      return url.pathname.startsWith("/api/")
        ? `${url.pathname}${url.search}`
        : null;
    } catch {
      return null;
    }
  }
  const index = trimmed.indexOf("/api/");
  if (index >= 0) return trimmed.slice(index);
  return trimmed.startsWith("/api/") ? trimmed : null;
}

export function platformConsoleBaseUrl(payload: unknown): string | null {
  let value = payload;
  for (let depth = 0; depth < 3; depth += 1) {
    const object = objectValue(value);
    if (!object) return null;
    const url = stringValue(
      object.console_base_url ?? object.consoleBaseUrl,
    );
    if (url) return normalizeConsoleUrl(url);
    if (!("data" in object)) return null;
    value = object.data;
  }
  return null;
}

export function inferPlatformAccessPath(baseUrl: string): string | null {
  try {
    const host = new URL(baseUrl).hostname.toLowerCase();
    const suffix = ".qwenpaw.platform.agentscope.io";
    if (!host.endsWith(suffix)) return null;
    const appId = host.slice(0, -suffix.length);
    if (!/^[a-z0-9-]+$/.test(appId)) return null;
    return `/api/v1/qwenpaw/${appId}`;
  } catch {
    return null;
  }
}

function normalizeConsoleUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
