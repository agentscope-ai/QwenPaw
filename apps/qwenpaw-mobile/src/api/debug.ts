export const DEFAULT_DEBUG_HOST = "127.0.0.1";
export const DEFAULT_DEBUG_PORT = 8088;

function normalizeDebugHost(value: string): string {
  const candidate = value.trim();
  if (!candidate) return DEFAULT_DEBUG_HOST;

  const urlHost = candidate.includes(":") && !candidate.startsWith("[")
    ? `[${candidate}]`
    : candidate;

  try {
    const parsed = new URL(`http://${urlHost}`);
    if (
      !parsed.hostname ||
      parsed.username ||
      parsed.password ||
      parsed.port ||
      parsed.pathname !== "/" ||
      parsed.search ||
      parsed.hash
    ) {
      return DEFAULT_DEBUG_HOST;
    }
    return parsed.hostname;
  } catch {
    return DEFAULT_DEBUG_HOST;
  }
}

function normalizeDebugPort(value: string): number {
  if (!/^\d+$/.test(value.trim())) return DEFAULT_DEBUG_PORT;

  const port = Number(value);
  return Number.isInteger(port) && port >= 1 && port <= 65535
    ? port
    : DEFAULT_DEBUG_PORT;
}

export function buildDebugBaseUrl(host: string, port: string): string {
  return `http://${normalizeDebugHost(host)}:${normalizeDebugPort(port)}`;
}
