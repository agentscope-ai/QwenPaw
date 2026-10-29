import api from "../api";
import { ApiError } from "../api/request";
import type {
  PoolDownloadJob,
  PoolDownloadState,
  SkillPoolDownloadRequest,
} from "../api/types";

/** How often the console asks the backend for the job's real state. */
export const POOL_DOWNLOAD_POLL_MS = 1_000;

/** Upper bound for the backoff applied while status polling keeps failing. */
export const POOL_DOWNLOAD_RETRY_MAX_MS = 5_000;

export interface PoolDownloadHandle {
  /** Resolves once the job reached a terminal state. */
  done: Promise<PoolDownloadJob>;
  /** Ask the backend to stop the job at its next safe point. */
  cancel: () => Promise<void>;
}

function isTerminal(state: PoolDownloadState): boolean {
  return state === "completed" || state === "failed" || state === "cancelled";
}

/**
 * A status request is worth retrying only while its failure says nothing about
 * the job itself: no response (network error, timeout) or a transient server
 * side status. A 404 means the job is gone and retrying would spin forever.
 */
function getErrorStatus(error: unknown): number | undefined {
  // `request()` throws ApiError, which carries the HTTP status directly.
  return error instanceof ApiError ? error.status : undefined;
}

function isRetryableStatusFailure(error: unknown): boolean {
  const status = getErrorStatus(error);
  // No status at all means the request never got an answer: retry it.
  if (status === undefined) return true;
  return status === 408 || status === 429 || status >= 500;
}

function retryDelay(consecutiveFailures: number): number {
  const backoff = POOL_DOWNLOAD_POLL_MS * 2 ** (consecutiveFailures - 1);
  return Math.min(backoff, POOL_DOWNLOAD_RETRY_MAX_MS);
}

/**
 * Start a pool download as a cancellable job and follow it to the end.
 *
 * There is deliberately no overall deadline: a broadcast to many workspaces
 * can legitimately take a long time, and the job keeps reporting its real
 * state — including `cancelling` while its rollback runs — until it reaches a
 * terminal one. Both `running` and `cancelling` are polled; only a terminal
 * answer stops tracking.
 *
 * Every answer — the start response, a poll and the cancel response — goes
 * through `accept`, and every failure through `fail`. That single path is
 * what keeps `done` and the state callbacks in agreement: once tracking has
 * ended, no late response can revive the dialog, and a fatal poll error
 * rejects `done` while also silencing those callbacks.
 */
export function startPoolDownloadJob(
  payload: SkillPoolDownloadRequest,
  options: { onState?: (state: PoolDownloadState) => void } = {},
): PoolDownloadHandle {
  const pollController = new AbortController();
  let pollTimer: number | null = null;
  let wakePoll: (() => void) | null = null;
  let ended = false;
  let cancelRequested = false;
  let lastConfirmedState: PoolDownloadState | null = null;

  let resolveDone!: (job: PoolDownloadJob) => void;
  let rejectDone!: (error: unknown) => void;
  const done = new Promise<PoolDownloadJob>((resolve, reject) => {
    resolveDone = resolve;
    rejectDone = reject;
  });

  /** End tracking once: no timer, no in-flight poll, no later callback. */
  const stopTracking = (): void => {
    ended = true;
    if (pollTimer !== null) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
    // Wake a sleeping poll so its loop can observe `ended` and return
    // instead of leaving a pending promise behind.
    const wake = wakePoll;
    wakePoll = null;
    wake?.();
    // Aborting a status request never cancels the installation: that is
    // still DELETE, with the backend's rollback.
    pollController.abort();
  };

  /** The one place a job result is accepted, whatever answered it. */
  const accept = (job: PoolDownloadJob): void => {
    if (ended) return;
    lastConfirmedState = job.state;
    if (isTerminal(job.state)) {
      stopTracking();
      resolveDone(job);
    }
    // While the user asked to cancel, a non-terminal answer still means the
    // rollback is in progress: keep showing that, not `running`.
    options.onState?.(
      cancelRequested && !isTerminal(job.state) ? "cancelling" : job.state,
    );
  };

  /** The one place a job failure is accepted. */
  const fail = (error: unknown): void => {
    if (ended) return;
    stopTracking();
    rejectDone(error);
  };

  const sleep = (ms: number): Promise<void> =>
    new Promise((resolve) => {
      wakePoll = resolve;
      pollTimer = window.setTimeout(() => {
        pollTimer = null;
        wakePoll = null;
        resolve();
      }, ms);
    });

  const poll = async (jobId: string): Promise<void> => {
    let failures = 0;
    while (!ended) {
      await sleep(
        failures === 0 ? POOL_DOWNLOAD_POLL_MS : retryDelay(failures),
      );
      if (ended) return;
      let job: PoolDownloadJob;
      try {
        job = await api.getSkillPoolDownload(jobId, {
          signal: pollController.signal,
          // `request()` only retries timeouts and network errors, and does
          // not retry by default. Let it own those, and keep HTTP status
          // backoff (408/429/5xx) in this loop.
          retries: Infinity,
        });
        failures = 0;
      } catch (error) {
        // Aborting the poll is how stopTracking ends this loop; an abort is
        // not a job failure.
        if (ended) return;
        if (!isRetryableStatusFailure(error)) {
          fail(error);
          return;
        }
        failures += 1;
        continue;
      }
      accept(job);
    }
  };

  // `Promise.resolve` keeps non-thenable responses (and tests that mock a
  // plain job) on the same path as the real, asynchronous request.
  const started = Promise.resolve(api.startSkillPoolDownload(payload));
  started.then((job) => {
    accept(job);
    if (!ended) void poll(job.job_id);
  }, fail);

  const cancel = async (): Promise<void> => {
    if (ended) return;
    cancelRequested = true;
    // Show "cancelling" before the request leaves, including while the
    // initial POST is still pending: the user asked, and the backend may
    // take a moment to acknowledge it.
    options.onState?.("cancelling");
    let job: PoolDownloadJob;
    try {
      job = await started;
    } catch {
      // The start failed; `done` already rejected with that same error.
      return;
    }
    if (ended) return;
    try {
      const response = await api.cancelSkillPoolDownload(job.job_id);
      accept(response);
    } catch (error) {
      // A response that arrives after tracking ended is stale: the job
      // already reached a terminal state through another path.
      if (ended) return;
      // The request never reached the backend, so nothing was cancelled.
      // Fall back to the state we can still prove and report the failure.
      cancelRequested = false;
      options.onState?.(lastConfirmedState ?? "running");
      throw error;
    }
  };

  return { done, cancel };
}
