const LARGE_BASE64_CHARS = 4_096;
const RAW_DISPLAY_CHAR_BUDGET = 100_000;
const RAW_DISPLAY_NODE_BUDGET = 2_000;
const RAW_DISPLAY_DEPTH_BUDGET = 100;

type BudgetKind = "character" | "node";

interface BudgetReport {
  kind: BudgetKind;
  /** Nodes visited before the walk ended (exact when kind is "character"). */
  nodes: number;
}

function budgetSummary(): string {
  return (
    `[Raw value omitted: exceeds the ${RAW_DISPLAY_NODE_BUDGET}-node ` +
    "display budget. Switch to Current view or rerun the tool with " +
    "narrower output.]"
  );
}

function truncationNotice(total: number, shown: number): string {
  return (
    `[Raw value truncated: showing the first ${shown} of ${total} ` +
    "characters. Switch to Current view for the full value.]"
  );
}

function leafTruncationNotice(omitted: number): string {
  return `…[truncated ${omitted} characters]`;
}

/**
 * Walk the value once, bounded by the node/depth budgets. Returns null when
 * the value fits the character budget; otherwise reports which budget was
 * exceeded. A "character" report implies the whole graph was walked, so its
 * node count is exact and safe to use as a truncation divisor.
 */
function inspectDisplayBudget(value: unknown): BudgetReport | null {
  let characters = 0;
  let nodes = 0;
  let nodeOverflow = false;
  const ancestors = new WeakSet<object>();

  const inspect = (item: unknown, depth: number): void => {
    if (nodeOverflow) return;
    nodes += 1;
    if (nodes > RAW_DISPLAY_NODE_BUDGET || depth > RAW_DISPLAY_DEPTH_BUDGET) {
      nodeOverflow = true;
      return;
    }

    if (typeof item === "string") {
      characters += item.length;
      return;
    }
    if (item === null || item === undefined) return;
    if (typeof item !== "object") {
      characters += String(item).length;
      return;
    }
    if (ancestors.has(item)) return;

    ancestors.add(item);
    if (Array.isArray(item)) {
      for (const child of item) {
        inspect(child, depth + 1);
        if (nodeOverflow) return;
      }
    } else {
      const container = item as Record<string, unknown>;
      for (const key in container) {
        if (!Object.prototype.hasOwnProperty.call(container, key)) continue;
        characters += key.length;
        inspect(container[key], depth + 1);
        if (nodeOverflow) return;
      }
    }
    ancestors.delete(item);
  };

  inspect(value, 0);
  if (nodeOverflow) return { kind: "node", nodes };
  if (characters > RAW_DISPLAY_CHAR_BUDGET) {
    return { kind: "character", nodes };
  }
  return null;
}

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
  leafLimit: number | null,
): unknown {
  if (Array.isArray(value)) {
    if (ancestors.has(value)) return "[circular reference]";
    ancestors.add(value);
    const sanitized = value.map((item) =>
      sanitizeForDisplay(item, ancestors, leafLimit),
    );
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
        return [key, sanitizeForDisplay(item, ancestors, leafLimit)];
      }),
    );
    ancestors.delete(value);
    return sanitized;
  }

  if (typeof value === "string" && leafLimit !== null) {
    return truncateText(value, leafLimit);
  }

  return value;
}

function truncateText(text: string, limit: number): string {
  if (text.length <= limit) return text;
  return text.slice(0, limit) + leafTruncationNotice(text.length - limit);
}

function capOutput(output: string): string {
  if (output.length <= RAW_DISPLAY_CHAR_BUDGET) return output;
  return (
    output.slice(0, RAW_DISPLAY_CHAR_BUDGET) +
    `\n${truncationNotice(output.length, RAW_DISPLAY_CHAR_BUDGET)}`
  );
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

  const report = inspectDisplayBudget(value);
  if (report?.kind === "node") return budgetSummary();

  if (typeof value === "string") {
    if (isLargeBase64DataUrl(value)) {
      return base64Placeholder(value.length);
    }
    if (report?.kind === "character") {
      // Oversized raw text: show its head without parsing or copying it.
      return capOutput(value);
    }
    const parsed = parseJsonString(value);
    if (typeof parsed === "string") {
      return isLargeBase64DataUrl(parsed)
        ? base64Placeholder(parsed.length)
        : parsed;
    }
    try {
      const sanitized = sanitizeForDisplay(parsed, new WeakSet<object>(), null);
      return capOutput(JSON.stringify(sanitized, null, 2) ?? value);
    } catch {
      return value;
    }
  }

  // Object graph: the walk completed, so the node count is a fair divisor
  // for a per-leaf character budget that keeps the structure visible.
  const leafLimit =
    report?.kind === "character"
      ? Math.max(1, Math.floor(RAW_DISPLAY_CHAR_BUDGET / report.nodes))
      : null;
  try {
    const sanitized = sanitizeForDisplay(
      value,
      new WeakSet<object>(),
      leafLimit,
    );
    return capOutput(JSON.stringify(sanitized, null, 2) ?? String(value));
  } catch {
    return String(value);
  }
}
