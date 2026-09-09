/**
 * Shared tone tokens for the production blueprint components. Token-only
 * colors (hard rule §5); mirrors the demo visual baseline without importing
 * demo data.
 */
export type BlueprintTone = "done" | "run" | "wait" | "idle";

export const TONE_TEXT: Record<BlueprintTone, string> = {
  done: "text-[var(--color-success)]",
  run: "text-[var(--color-primary,#3b82f6)]",
  wait: "text-[var(--color-warning)]",
  idle: "text-[var(--color-text-tertiary)]",
};

export const TONE_CHIP: Record<BlueprintTone, string> = {
  done: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  run: "bg-[rgba(59,130,246,.1)] text-[var(--color-primary,#3b82f6)]",
  wait: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
  idle: "bg-[var(--color-bg-secondary)] text-[var(--color-text-tertiary)]",
};

export const TONE_DOT: Record<BlueprintTone, string> = {
  done: "bg-[var(--color-success)]",
  run: "bg-[var(--color-primary,#3b82f6)]",
  wait: "bg-[var(--color-warning)]",
  idle: "bg-[var(--color-border-strong)]",
};
