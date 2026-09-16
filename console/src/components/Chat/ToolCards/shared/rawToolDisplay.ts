const LARGE_BASE64_CHARS = 4_096;

function base64Placeholder(length: number): string {
  return `[base64 data omitted: ${length} characters]`;
}

function isLargeBase64DataUrl(value: string): boolean {
  if (
    value.length <= LARGE_BASE64_CHARS ||
    value.slice(0, 5).toLowerCase() !== "data:"
  ) {
    return false;
  }

  const commaIndex = value.indexOf(",", 5);
  if (commaIndex < 5 || commaIndex > 256) return false;

  const header = value.slice(0, commaIndex).toLowerCase();
  return header.startsWith("data:") && header.endsWith(";base64");
}

function isBase64Field(
  key: string,
  container: Record<string, unknown>,
): boolean {
  const normalizedKey = key.toLowerCase();
  return (
    normalizedKey.includes("base64") ||
    normalizedKey === "b64_json" ||
    (normalizedKey === "data" &&
      (container.type === "base64" || container.encoding === "base64"))
  );
}

function sanitizeForDisplay(
  value: unknown,
  ancestors: WeakSet<object>,
): unknown {
  if (Array.isArray(value)) {
    if (ancestors.has(value)) return "[circular reference]";
    ancestors.add(value);
    const sanitized = value.map((item) => sanitizeForDisplay(item, ancestors));
    ancestors.delete(value);
    return sanitized;
  }

  if (value && typeof value === "object") {
    if (ancestors.has(value)) return "[circular reference]";
    ancestors.add(value);
    const container = value as Record<string, unknown>;
    const sanitized = Object.fromEntries(
      Object.entries(container).map(([key, item]) => {
        if (
          typeof item === "string" &&
          (isLargeBase64DataUrl(item) ||
            (item.length > LARGE_BASE64_CHARS && isBase64Field(key, container)))
        ) {
          return [key, base64Placeholder(item.length)];
        }
        return [key, sanitizeForDisplay(item, ancestors)];
      }),
    );
    ancestors.delete(value);
    return sanitized;
  }

  return value;
}

function parseJsonString(value: string): unknown {
  const trimmed = value.trim();
  if (
    !(
      (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
      (trimmed.startsWith("[") && trimmed.endsWith("]"))
    )
  ) {
    return value;
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

/** Format raw tool data for readable JSON display without mutating its value. */
export function formatRawToolValue(value: unknown): string {
  if (value === undefined) return "";

  const parsed = typeof value === "string" ? parseJsonString(value) : value;
  if (typeof parsed === "string") {
    return isLargeBase64DataUrl(parsed)
      ? base64Placeholder(parsed.length)
      : parsed;
  }

  try {
    const sanitized = sanitizeForDisplay(parsed, new WeakSet<object>());
    return JSON.stringify(sanitized, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}
