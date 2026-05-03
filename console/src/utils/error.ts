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
