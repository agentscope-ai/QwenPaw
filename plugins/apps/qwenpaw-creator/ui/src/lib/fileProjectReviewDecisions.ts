import type {
  FileProjectReviewOperation,
  FileProjectReviewRecord,
} from "@/contracts/creator";

/** Matches the backend auto_snapshot producer, not a user-facing title. */
const AUTO_SNAPSHOT_DESCRIPTION = "自动快照：修改前的时间轴副本";

/**
 * Only proven automatic version bookkeeping is exempt from human decisions.
 * Keep this contract aligned with project_files/review_bookkeeping.py. The
 * backend retains the audit operations and resolves legacy pending records;
 * this presentation guard never sends an implicit ACCEPT or edits the project.
 */
export function isSystemVersionReviewOperation(
  operation: FileProjectReviewOperation,
): boolean {
  const tokens = (operation.json_pointer ?? "")
    .split("/")
    .slice(1)
    .map((token) => token.replace(/~1/gu, "/").replace(/~0/gu, "~"));
  if (
    tokens.length >= 7 &&
    tokens[0] === "timelines" &&
    tokens[1] === "items" &&
    tokens[3] === "elements_by_id" &&
    tokens[5] === "creation" &&
    ["shots", "min_dialogue_ratio", "prompt_sync"].includes(tokens[6])
  )
    return true;
  if (
    tokens.length === 3 &&
    tokens[0] === "timelines" &&
    tokens[1] === "items" &&
    tokens[2].startsWith("snapshot:") &&
    operation.kind === "create" &&
    operation.before == null &&
    operation.after !== null &&
    typeof operation.after === "object" &&
    !Array.isArray(operation.after)
  ) {
    const after = operation.after as Record<string, unknown>;
    return (
      after.timeline_id === tokens[2] &&
      after.description === AUTO_SNAPSHOT_DESCRIPTION
    );
  }
  if (operation.json_pointer !== "/timelines/order") return false;
  const { before, after } = operation;
  if (
    !Array.isArray(before) ||
    !Array.isArray(after) ||
    !before.every((id) => typeof id === "string") ||
    !after.every((id) => typeof id === "string") ||
    JSON.stringify(before) === JSON.stringify(after)
  )
    return false;
  const live = (ids: string[]) =>
    ids.filter((id) => !id.startsWith("snapshot:"));
  return JSON.stringify(live(before)) === JSON.stringify(live(after));
}

export function userReviewOperations(
  review: FileProjectReviewRecord,
): FileProjectReviewOperation[] {
  return review.operations.filter(
    (operation) => !isSystemVersionReviewOperation(operation),
  );
}

export function pendingUserReviewOperations(
  review: FileProjectReviewRecord,
): FileProjectReviewOperation[] {
  return userReviewOperations(review).filter(
    (operation) => operation.decision === "PENDING",
  );
}
