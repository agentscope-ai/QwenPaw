export interface ContextUsage {
  totalTokens: number;
  maxInputLength: number;
  pct: number;
  totalMessages?: number;
}

export function parseContextUsage(payload: unknown): ContextUsage | null {
  if (!payload || typeof payload !== "object") return null;

  const raw = (payload as Record<string, unknown>).context_usage;
  if (!raw || typeof raw !== "object") return null;

  const record = raw as Record<string, unknown>;
  const totalTokens = Number(record.total_tokens);
  const maxInputLength = Number(record.max_input_length);
  const pct = Number(record.pct);

  if (
    !Number.isFinite(totalTokens) ||
    !Number.isFinite(maxInputLength) ||
    !Number.isFinite(pct)
  ) {
    return null;
  }

  const totalMessages = Number(record.total_messages);
  return {
    totalTokens,
    maxInputLength,
    pct,
    totalMessages: Number.isFinite(totalMessages) ? totalMessages : undefined,
  };
}

export function formatContextTokens(value: number): string {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return `${Math.max(0, Math.round(value))}`;
}

export function contextUsageLevel(
  pct: number,
): "normal" | "warning" | "danger" {
  if (pct >= 70) return "danger";
  if (pct >= 50) return "warning";
  return "normal";
}
