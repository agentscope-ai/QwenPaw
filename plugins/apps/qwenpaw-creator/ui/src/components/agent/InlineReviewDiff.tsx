/**
 * Inline review diff rendered at the place the reviewed text actually lives.
 *
 * The review panel intentionally does NOT render text diffs anymore: clicking
 * "查看" navigates to the field (matched by data-creator-path == the review
 * operation's JSON pointer) and this component shows the red/green diff right
 * below the original content, together with "保留"/"撤销" (keep/undo) decision
 * buttons.
 */

import { useState } from "react";
import { message } from "antd";
import { Check, FileDiff, Undo2 } from "lucide-react";
import type {
  FileProjectReviewOperation,
  FileProjectReviewRecord,
} from "@/contracts/creator";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import DiffView from "./DiffView";

const MISSING = Symbol("missing");

function tokensOf(pointer: string): string[] | null {
  if (!pointer.startsWith("/")) return null;
  return pointer
    .slice(1)
    .split("/")
    .map((token) => token.replace(/~1/g, "/").replace(/~0/g, "~"));
}

function valueAt(value: unknown, tokens: string[]): unknown {
  let current: unknown = value;
  for (const token of tokens) {
    if (Array.isArray(current)) {
      const index = Number(token);
      if (!Number.isInteger(index) || index < 0 || index >= current.length)
        return MISSING;
      current = current[index];
    } else if (current !== null && typeof current === "object") {
      const record = current as Record<string, unknown>;
      if (!(token in record)) return MISSING;
      current = record[token];
    } else {
      return MISSING;
    }
  }
  return current;
}

function isPrefix(prefix: string[], tokens: string[]): boolean {
  if (prefix.length > tokens.length) return false;
  return prefix.every((token, index) => tokens[index] === token);
}

export interface MatchedReviewOperation {
  review: FileProjectReviewRecord;
  operation: FileProjectReviewOperation;
  before: unknown;
  after: unknown;
  /**
   * exact: the change pointer matches the field exactly;
   * ancestor: the change covers a wider range than this field (the decision
   * applies to the whole change);
   * descendant: the change happens on a sub-path inside this field.
   */
  relation: "exact" | "ancestor" | "descendant";
  subPath: string | null;
}

/** Pending review operations that overlap one field's JSON pointer. */
export function matchReviewOperations(
  reviews: FileProjectReviewRecord[],
  pointer: string,
): MatchedReviewOperation[] {
  const fieldTokens = tokensOf(pointer);
  if (!fieldTokens) return [];
  const matches: MatchedReviewOperation[] = [];
  for (const review of reviews) {
    if (review.status !== "PENDING") continue;
    for (const operation of review.operations) {
      if (operation.decision !== "PENDING") continue;
      if (!operation.json_pointer) continue;
      const opTokens = tokensOf(operation.json_pointer);
      if (!opTokens) continue;
      if (opTokens.length === fieldTokens.length) {
        if (!isPrefix(opTokens, fieldTokens)) continue;
        matches.push({
          review,
          operation,
          before: operation.before,
          after: operation.after,
          relation: "exact",
          subPath: null,
        });
      } else if (isPrefix(opTokens, fieldTokens)) {
        // The operation replaced an ancestor object; extract this field's
        // slice of the before/after payloads so the diff stays field-level.
        const rest = fieldTokens.slice(opTokens.length);
        const before = valueAt(operation.before, rest);
        const after = valueAt(operation.after, rest);
        if (before === MISSING && after === MISSING) continue;
        if (JSON.stringify(before) === JSON.stringify(after)) continue;
        matches.push({
          review,
          operation,
          before: before === MISSING ? null : before,
          after: after === MISSING ? null : after,
          relation: "ancestor",
          subPath: null,
        });
      } else if (isPrefix(fieldTokens, opTokens)) {
        matches.push({
          review,
          operation,
          before: operation.before,
          after: operation.after,
          relation: "descendant",
          subPath: `/${opTokens.slice(fieldTokens.length).join("/")}`,
        });
      }
    }
  }
  return matches;
}

export default function InlineReviewDiff({ pointer }: { pointer: string }) {
  const projectId = useFileProjectReviewStore((state) => state.projectId);
  const reviews = useFileProjectReviewStore((state) => state.reviews);
  const decide = useFileProjectReviewStore((state) => state.decide);
  const decisionInFlight = useFileProjectReviewStore(
    (state) => state.decisionInFlight,
  );
  const [localBusy, setLocalBusy] = useState(false);
  const matches = matchReviewOperations(reviews, pointer);
  if (!projectId || matches.length === 0) return null;
  const busy = decisionInFlight || localBusy;

  const submit = async (
    match: MatchedReviewOperation,
    decision: "ACCEPT" | "REJECT",
  ) => {
    setLocalBusy(true);
    try {
      await decide(projectId, match.review.review_id, [
        {
          operation_id: match.operation.operation_id,
          decision,
        },
      ]);
      message.success(decision === "ACCEPT" ? "已保留该修改" : "已撤销该修改");
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setLocalBusy(false);
    }
  };

  return (
    <div className="mt-1.5 space-y-1.5">
      {matches.map((match) => (
        <div
          key={`${match.operation.operation_id}-${match.subPath ?? ""}`}
          data-review-inline-diff={match.operation.operation_id}
          className="rounded-lg border border-[var(--color-accent)]/40 bg-[var(--color-bg-card)] p-2"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="flex min-w-0 items-center gap-1 text-[10px] font-semibold text-[var(--color-accent)]">
              <FileDiff className="h-3 w-3 shrink-0" />
              待审修改
              {match.subPath && (
                <span
                  className="truncate font-mono font-normal text-[var(--color-text-tertiary)]"
                  title={match.subPath}
                >
                  {match.subPath}
                </span>
              )}
            </p>
            <div className="flex shrink-0 gap-1">
              <button
                type="button"
                aria-label="保留该修改"
                disabled={busy}
                onClick={() => void submit(match, "ACCEPT")}
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)] disabled:opacity-50"
              >
                <Check className="h-3 w-3" />
                保留
              </button>
              <button
                type="button"
                aria-label="撤销该修改"
                disabled={busy}
                onClick={() => void submit(match, "REJECT")}
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)] disabled:opacity-50"
              >
                <Undo2 className="h-3 w-3" />
                撤销
              </button>
            </div>
          </div>
          <div className="mt-1.5">
            <DiffView before={match.before} after={match.after} />
          </div>
          {match.relation === "ancestor" && (
            <p className="mt-1 text-[9px] text-[var(--color-text-tertiary)]">
              该决策将作用于本次修改覆盖的完整范围。
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
