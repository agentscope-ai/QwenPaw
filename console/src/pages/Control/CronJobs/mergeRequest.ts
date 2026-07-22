import type { CronJobRequest } from "../../../api/types";

export function mergeCronJobRequest(
  existing: CronJobRequest | undefined,
  submitted: Partial<CronJobRequest> | undefined,
): CronJobRequest {
  return {
    input: [],
    ...existing,
    ...submitted,
  };
}
