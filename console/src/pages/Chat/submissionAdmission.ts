export type SubmissionAdmission = "direct" | "queue";

export interface SubmissionAdmissionState {
  pendingDirectSubmission: boolean;
  targetIsCurrent: boolean;
  owner: boolean;
  frontendBusy: boolean;
  usesQwenPawBackend: boolean;
  backendStatus: "idle" | "running" | "unknown";
}

/**
 * Decide whether a message may use the SDK's direct transport. Keeping this
 * policy pure makes the async admission gate deterministic and testable.
 */
export function decideSubmissionAdmission(
  state: SubmissionAdmissionState,
): SubmissionAdmission {
  if (
    state.pendingDirectSubmission ||
    !state.targetIsCurrent ||
    !state.owner ||
    state.frontendBusy
  ) {
    return "queue";
  }
  if (state.usesQwenPawBackend && state.backendStatus === "running") {
    return "queue";
  }
  return "direct";
}
