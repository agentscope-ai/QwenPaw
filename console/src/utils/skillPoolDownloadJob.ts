import api from "../api";
import type {
  PoolDownloadJob,
  PoolDownloadState,
  SkillPoolDownloadRequest,
} from "../api/types";

/** How often the console asks the backend for the job's real state. */
export const POOL_DOWNLOAD_POLL_MS = 1_000;

export interface PoolDownloadHandle {
  /** Resolves once the job reached a terminal state. */
  done: Promise<PoolDownloadJob>;
  /** Ask the backend to stop the job at its next safe point. */
  cancel: () => Promise<void>;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isTerminal(state: PoolDownloadState): boolean {
  return state === "completed" || state === "failed" || state === "cancelled";
}

/**
 * Start a pool download as a cancellable job and follow it to the end.
 *
 * There is deliberately no overall deadline: a broadcast to many workspaces
 * can legitimately take a long time, and the job keeps reporting its real
 * state — including `cancelling` while its rollback runs — until it reaches a
 * terminal one.
 */
export function startPoolDownloadJob(
  payload: SkillPoolDownloadRequest,
  options: { onState?: (state: PoolDownloadState) => void } = {},
): PoolDownloadHandle {
  const started = api.startSkillPoolDownload(payload);

  const cancel = async (): Promise<void> => {
    const job = await started;
    const cancelling = await api.cancelSkillPoolDownload(job.job_id);
    options.onState?.(cancelling.state);
  };

  const done = (async (): Promise<PoolDownloadJob> => {
    let job = await started;
    options.onState?.(job.state);
    while (!isTerminal(job.state)) {
      await delay(POOL_DOWNLOAD_POLL_MS);
      job = await api.getSkillPoolDownload(job.job_id);
      options.onState?.(job.state);
    }
    return job;
  })();

  return { done, cancel };
}
