/** MCP client key: letters, digits, hyphen, underscore; max 100 chars. */
export const MCP_CLIENT_KEY_MAX_LEN = 100;

export const MCP_CLIENT_KEY_REGEX = /^[A-Za-z0-9_-]{1,100}$/;

const RESERVED_PREFIXES = ["tools/", "toggle/", "oauth/", "reconnect/"];
const RESERVED_EXACT = ["tools", "toggle", "oauth", "reconnect"];

export type McpClientKeyErrorCode =
  | "empty"
  | "tooLong"
  | "invalidChars"
  | "reserved";

export function normalizeMcpClientKey(key: string): string {
  return key.trim();
}

export function getMcpClientKeyErrorCode(
  key: string,
): McpClientKeyErrorCode | null {
  const normalized = normalizeMcpClientKey(key);
  if (!normalized) return "empty";
  if (normalized.length > MCP_CLIENT_KEY_MAX_LEN) return "tooLong";
  if (!MCP_CLIENT_KEY_REGEX.test(normalized)) return "invalidChars";
  const lower = normalized.toLowerCase();
  if (RESERVED_EXACT.includes(lower)) return "reserved";
  for (const prefix of RESERVED_PREFIXES) {
    if (lower.startsWith(prefix)) return "reserved";
  }
  return null;
}

export function isValidMcpClientKey(key: string): boolean {
  return getMcpClientKeyErrorCode(key) === null;
}

type TranslateFn = (key: string, options?: Record<string, string>) => string;

/** Localized validation message for UI and JSON import. */
export function getMcpClientKeyErrorMessage(
  key: string,
  t: TranslateFn,
): string | null {
  const code = getMcpClientKeyErrorCode(key);
  if (!code) return null;
  const reason = t(`mcp.keyValidation.${code}`);
  const normalized = normalizeMcpClientKey(key);
  if (normalized) {
    return t("mcp.keyValidation.invalidKey", { key: normalized, reason });
  }
  return reason;
}
