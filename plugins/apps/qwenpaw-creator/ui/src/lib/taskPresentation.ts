function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function recordOf(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Render the Runtime Task progress contract; always normalized to [0, 1]. */
export function taskProgressPercent(
  progress: number | null | undefined,
): number | null {
  if (progress == null || !Number.isFinite(progress)) return null;
  return Math.round(Math.max(0, Math.min(1, progress)) * 100);
}

/** Prefer durable structured provider/item failures over generic status. */
export function taskErrorMessage(error: unknown, fallback: string): string {
  const directText = nonEmptyString(error);
  if (directText) return directText;

  const record = recordOf(error);
  if (!record) return fallback;

  const direct =
    nonEmptyString(record.message) || nonEmptyString(record.detail);
  if (direct) return direct;

  if (Array.isArray(record.items)) {
    const itemErrors = record.items.flatMap((item) => {
      const itemRecord = recordOf(item);
      if (!itemRecord) return [];
      const detail =
        nonEmptyString(itemRecord.error) ||
        nonEmptyString(itemRecord.message) ||
        nonEmptyString(itemRecord.detail);
      return detail ? [detail] : [];
    });
    const unique = [...new Set(itemErrors)];
    if (unique.length > 0) return unique.join("；");
  }

  return nonEmptyString(record.code) || nonEmptyString(record.kind) || fallback;
}
