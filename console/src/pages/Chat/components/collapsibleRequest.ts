/**
 * components/collapsibleRequest.ts — shared helpers for
 * CollapsibleRequestCard. Kept in a non-component module so the component
 * file only exports components (react-refresh rule).
 */
import { extractUserMessageText } from "../utils";

/** Messages whose combined text exceeds this are collapsed by default. */
export const COLLAPSE_THRESHOLD = 2000;
/** How many leading characters the collapsed summary shows. */
export const SUMMARY_LENGTH = 300;

/** Extract the combined plain text of a request card's input messages. */
export function extractRequestText(data: unknown): string {
  const input = (data as { input?: unknown } | null)?.input;
  if (!Array.isArray(input)) return "";
  return input
    .map((m) => extractUserMessageText(m))
    .join("\n")
    .trim();
}
