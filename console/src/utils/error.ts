export function parseErrorDetail(error: unknown): Record<string, any> | null {
  if (!(error instanceof Error)) return null;
  const msg = error.message;
  // Try " - " separator first (from request.ts formatted errors)
  const idx = msg.indexOf(" - ");
  if (idx !== -1) {
    try {
      const parsed = JSON.parse(msg.slice(idx + 3));
      return parsed?.detail || parsed;
    } catch {
      // fall through to raw JSON attempt
    }
  }
  // Fallback: try parsing the entire message as JSON
  try {
    const parsed = JSON.parse(msg);
    if (typeof parsed === "object" && parsed !== null) {
      return parsed?.detail || parsed;
    }
  } catch {
    // not JSON
  }
  return null;
}

/** Flatten a FastAPI validation detail into readable "field: reason" text. */
export function summarizeValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail)) {
    // Semantic failures (e.g. an unavailable memory backend) report a plain
    // object instead of a list of schema errors.
    if (!detail || typeof detail !== "object") return null;
    const entries = Object.entries(detail as Record<string, unknown>)
      .filter(
        ([, value]) =>
          typeof value === "string" ||
          typeof value === "number" ||
          typeof value === "boolean",
      )
      .map(([key, value]) => `${key}: ${value}`);
    return entries.length ? entries.join("; ") : null;
  }
  if (detail.length === 0) return null;
  const parts = detail
    .map((entry) => {
      if (!entry || typeof entry !== "object") return null;
      const { loc, msg } = entry as { loc?: unknown; msg?: unknown };
      const field = Array.isArray(loc)
        ? loc
            .filter((part) => part !== "body")
            .map((part) => String(part))
            .join(".")
        : "";
      const reason = typeof msg === "string" ? msg : "";
      if (!field && !reason) return null;
      return field && reason ? `${field}: ${reason}` : field || reason;
    })
    .filter((part): part is string => Boolean(part));
  return parts.length ? parts.join("; ") : null;
}
