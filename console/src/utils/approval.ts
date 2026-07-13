export type ToolExecutionLevel = "STRICT" | "SMART" | "AUTO" | "OFF";

export const LEVELS: readonly ToolExecutionLevel[] = [
  "STRICT",
  "SMART",
  "AUTO",
  "OFF",
];

export function normalizeLevel(raw: string | undefined): ToolExecutionLevel {
  const upper = (raw || "AUTO").toUpperCase();
  return LEVELS.includes(upper as ToolExecutionLevel)
    ? (upper as ToolExecutionLevel)
    : "AUTO";
}
