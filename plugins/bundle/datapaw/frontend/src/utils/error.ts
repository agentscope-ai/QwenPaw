export function parseErrorDetail(error: unknown): Record<string, any> | null {
  if (!(error instanceof Error)) return null;
  const idx = error.message.indexOf(" - ");
  if (idx === -1) return null;
  try {
    const parsed = JSON.parse(error.message.slice(idx + 3));
    return parsed?.detail || parsed;
  } catch {
    return null;
  }
}
