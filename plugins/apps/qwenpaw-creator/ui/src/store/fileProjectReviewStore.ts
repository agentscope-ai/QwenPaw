import { create } from "zustand";
import {
  CreatorHttpError,
  decideFileProjectReview,
  getActiveFileProjectReview,
  newClientId,
} from "@/api/creator";
import type {
  FileProjectReviewDecisionItem,
  FileProjectReviewRejectionFeedback,
  FileProjectReviewRecord,
} from "@/contracts/creator";

export type FileProjectReviewSyncStatus =
  | "idle"
  | "syncing"
  | "healthy"
  | "degraded"
  | "not_found";

export interface FileProjectReviewPollOptions {
  activeIntervalMs: number;
  hiddenIntervalMs: number;
  retryBaseMs: number;
  maxBackoffMs: number;
  jitterRatio: number;
  random: () => number;
}

export const DEFAULT_FILE_PROJECT_REVIEW_POLL_OPTIONS: FileProjectReviewPollOptions =
  {
    activeIntervalMs: 2_000,
    hiddenIntervalMs: 15_000,
    retryBaseMs: 1_000,
    maxBackoffMs: 30_000,
    jitterRatio: 0.15,
    random: Math.random,
  };

export interface FileProjectReviewState {
  projectId: string | null;
  reviews: FileProjectReviewRecord[];
  etag: string | null;
  syncStatus: FileProjectReviewSyncStatus;
  syncError: string | null;
  lastGoodAt: string | null;
  requestInFlight: boolean;
  decisionInFlight: boolean;
  polling: boolean;
  consecutiveFailures: number;
  reset: (projectId?: string | null) => void;
  pollOnce: (projectId: string) => Promise<void>;
  decide: (
    projectId: string,
    reviewId: string,
    decisions: FileProjectReviewDecisionItem[],
    rejectionFeedback?: FileProjectReviewRejectionFeedback,
  ) => Promise<FileProjectReviewRecord>;
  startPolling: (
    projectId: string,
    options?: Partial<FileProjectReviewPollOptions>,
  ) => () => void;
  stopPolling: (projectId?: string) => void;
}

interface PollController {
  token: number;
  projectId: string;
  options: FileProjectReviewPollOptions;
  timer: number | null;
  running: boolean;
  visibilityHandler: () => void;
}

const reviewBase = (projectId: string | null = null) => ({
  projectId,
  reviews: [] as FileProjectReviewRecord[],
  etag: null,
  syncStatus: "idle" as FileProjectReviewSyncStatus,
  syncError: null,
  lastGoodAt: null,
  requestInFlight: false,
  decisionInFlight: false,
  polling: false,
  consecutiveFailures: 0,
});

function semanticEtag(value: string): string {
  return value.trim().replace(/^W\//, "").replace(/^"|"$/g, "");
}

function quotedEtag(value: string): string {
  return `"${semanticEtag(value)}"`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isPageVisible(): boolean {
  return (
    typeof document === "undefined" || document.visibilityState !== "hidden"
  );
}

function jitteredDelay(
  delay: number,
  options: FileProjectReviewPollOptions,
): number {
  const ratio = Math.max(0, Math.min(1, options.jitterRatio));
  const sample = Math.max(0, Math.min(1, options.random()));
  const offset = (sample * 2 - 1) * ratio;
  return Math.max(0, Math.round(delay * (1 + offset)));
}

function sameReviewPayload(
  left: FileProjectReviewRecord,
  right: FileProjectReviewRecord,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export const useFileProjectReviewStore = create<FileProjectReviewState>(
  (set, get) => {
    let projectEpoch = 0;
    let nextControllerToken = 0;
    let controller: PollController | null = null;
    const inFlightByProject = new Map<string, Promise<void>>();
    const retryDecisionIds = new Map<string, string>();

    const decisionRetryKey = (
      projectId: string,
      reviewId: string,
      decisionToken: string,
      decisions: FileProjectReviewDecisionItem[],
      rejectionFeedback?: FileProjectReviewRejectionFeedback,
    ) =>
      JSON.stringify({
        projectId,
        reviewId,
        decisionToken: semanticEtag(decisionToken),
        decisions: [...decisions].sort(
          (left, right) =>
            left.operation_id.localeCompare(right.operation_id) ||
            left.decision.localeCompare(right.decision),
        ),
        rejectionFeedback,
      });

    const ensureProject = (projectId: string) => {
      if (get().projectId === projectId) return;
      projectEpoch += 1;
      set(reviewBase(projectId));
    };

    const stopController = (projectId?: string) => {
      if (!controller || (projectId && controller.projectId !== projectId))
        return;
      const stoppedProjectId = controller.projectId;
      if (controller.timer !== null) window.clearTimeout(controller.timer);
      if (typeof document !== "undefined") {
        document.removeEventListener(
          "visibilitychange",
          controller.visibilityHandler,
        );
      }
      controller = null;
      set((state) =>
        state.projectId === stoppedProjectId ? { polling: false } : {},
      );
    };

    const pollOnce = (projectId: string): Promise<void> => {
      const existing = inFlightByProject.get(projectId);
      if (existing) return existing;
      ensureProject(projectId);
      if (get().decisionInFlight) return Promise.resolve();

      const epoch = projectEpoch;
      const requestEtag = get().etag;
      set((state) =>
        state.projectId === projectId
          ? {
              requestInFlight: true,
              syncStatus:
                state.reviews.length > 0 ? state.syncStatus : "syncing",
            }
          : {},
      );

      const request = (async () => {
        try {
          const result = await getActiveFileProjectReview(
            projectId,
            requestEtag,
          );
          set((state) => {
            if (epoch !== projectEpoch || state.projectId !== projectId)
              return {};
            if (result.kind === "empty") {
              return {
                reviews: [],
                etag: null,
                requestInFlight: false,
                syncStatus: "healthy" as const,
                syncError: null,
                consecutiveFailures: 0,
                lastGoodAt: new Date().toISOString(),
              };
            }
            if (result.kind === "not_modified") {
              if (state.reviews.length === 0 || !state.etag) {
                return {
                  requestInFlight: false,
                  syncStatus: "degraded" as const,
                  syncError:
                    "Active Reviews returned 304 before a last-good Review was loaded",
                  consecutiveFailures: state.consecutiveFailures + 1,
                };
              }
              if (
                result.etag &&
                semanticEtag(result.etag) !== semanticEtag(state.etag)
              ) {
                return {
                  requestInFlight: false,
                  syncStatus: "degraded" as const,
                  syncError:
                    "Active Reviews 304 ETag does not match the last-good decision tokens",
                  consecutiveFailures: state.consecutiveFailures + 1,
                };
              }
              return {
                requestInFlight: false,
                etag: result.etag ?? state.etag,
                syncStatus: "healthy" as const,
                syncError: null,
                consecutiveFailures: 0,
              };
            }

            const incomingReviews = result.reviews;
            const currentReviews = state.reviews;
            const currentMaxGeneration =
              currentReviews.length > 0
                ? Math.max(...currentReviews.map((r) => r.candidate_generation))
                : -1;
            const incomingMaxGeneration =
              incomingReviews.length > 0
                ? Math.max(
                    ...incomingReviews.map((r) => r.candidate_generation),
                  )
                : -1;
            if (
              currentReviews.length > 0 &&
              incomingMaxGeneration < currentMaxGeneration
            ) {
              return { requestInFlight: false };
            }
            const pendingReviews = incomingReviews.filter(
              (r) => r.status === "PENDING",
            );
            return {
              reviews: pendingReviews,
              etag: result.etag,
              requestInFlight: false,
              syncStatus: "healthy" as const,
              syncError: null,
              consecutiveFailures: 0,
              lastGoodAt: new Date().toISOString(),
            };
          });
        } catch (error) {
          const notFound =
            error instanceof CreatorHttpError && error.status === 404;
          set((state) => {
            if (epoch !== projectEpoch || state.projectId !== projectId)
              return {};
            if (notFound) {
              return {
                ...reviewBase(projectId),
                polling: state.polling,
                syncStatus: "not_found" as const,
                syncError: errorMessage(error),
              };
            }
            return {
              requestInFlight: false,
              syncStatus: "degraded" as const,
              syncError: errorMessage(error),
              consecutiveFailures: state.consecutiveFailures + 1,
            };
          });
          if (
            notFound &&
            epoch === projectEpoch &&
            get().projectId === projectId
          ) {
            stopController(projectId);
          }
        }
      })();
      inFlightByProject.set(projectId, request);
      void request.finally(() => {
        if (inFlightByProject.get(projectId) === request)
          inFlightByProject.delete(projectId);
      });
      return request;
    };

    const decide = async (
      projectId: string,
      reviewId: string,
      decisions: FileProjectReviewDecisionItem[],
      rejectionFeedback?: FileProjectReviewRejectionFeedback,
    ): Promise<FileProjectReviewRecord> => {
      ensureProject(projectId);
      const state = get();
      const review = state.reviews.find((r) => r.review_id === reviewId);
      if (!review || review.status !== "PENDING")
        throw new Error("没有可处理的文件 Review");
      if (state.decisionInFlight) throw new Error("文件 Review 决策正在提交");
      if (decisions.length === 0) throw new Error("至少需要一个 Review 决策");

      const ids = new Set(decisions.map((item) => item.operation_id));
      if (ids.size !== decisions.length)
        throw new Error("Review 决策不能包含重复 operation_id");
      const pendingIds = new Set(
        review.operations
          .filter((operation) => operation.decision === "PENDING")
          .map((operation) => operation.operation_id),
      );
      if ([...ids].some((operationId) => !pendingIds.has(operationId))) {
        throw new Error("Review operation 已处理或不存在");
      }
      if (
        rejectionFeedback &&
        !decisions.some((item) => item.decision === "REJECT")
      ) {
        throw new Error("撤销反馈必须对应至少一个 REJECT 决策");
      }

      const epoch = projectEpoch;
      const decisionToken = review.decision_token;
      const canonicalDecisions = [...decisions].sort(
        (left, right) =>
          left.operation_id.localeCompare(right.operation_id) ||
          left.decision.localeCompare(right.decision),
      );
      const retryKey = decisionRetryKey(
        projectId,
        reviewId,
        decisionToken,
        canonicalDecisions,
        rejectionFeedback,
      );
      const decisionId =
        retryDecisionIds.get(retryKey) ?? newClientId("file-review-decision");
      retryDecisionIds.set(retryKey, decisionId);
      set({ decisionInFlight: true, syncError: null });
      try {
        const result = await decideFileProjectReview(
          projectId,
          reviewId,
          {
            decisionId,
            decisionToken,
            decisions: canonicalDecisions,
            ...(rejectionFeedback ? { rejectionFeedback } : {}),
          },
          decisionId,
        );
        retryDecisionIds.delete(retryKey);
        set((current) => {
          if (epoch !== projectEpoch || current.projectId !== projectId)
            return {};
          const updatedReviews = current.reviews.filter(
            (r) => r.review_id !== reviewId,
          );
          if (result.status === "PENDING") {
            updatedReviews.push(result);
            updatedReviews.sort(
              (a, b) =>
                new Date(a.created_at).getTime() -
                new Date(b.created_at).getTime(),
            );
          }
          const compositeToken =
            updatedReviews.length > 0
              ? updatedReviews.map((r) => r.decision_token).join("|")
              : null;
          return {
            reviews: updatedReviews,
            etag: compositeToken ? quotedEtag(compositeToken) : null,
            decisionInFlight: false,
            syncStatus: "healthy" as const,
            syncError: null,
            consecutiveFailures: 0,
            lastGoodAt: new Date().toISOString(),
          };
        });
        return result;
      } catch (error) {
        set((current) =>
          epoch === projectEpoch && current.projectId === projectId
            ? {
                decisionInFlight: false,
                syncStatus: "degraded" as const,
                syncError: errorMessage(error),
                consecutiveFailures: current.consecutiveFailures + 1,
              }
            : {},
        );
        throw error;
      }
    };

    const schedule = (active: PollController) => {
      if (controller !== active || active.running) return;
      if (active.timer !== null) window.clearTimeout(active.timer);
      const failures =
        get().projectId === active.projectId ? get().consecutiveFailures : 0;
      const regularDelay = isPageVisible()
        ? active.options.activeIntervalMs
        : active.options.hiddenIntervalMs;
      const retryDelay = Math.min(
        active.options.maxBackoffMs,
        active.options.retryBaseMs *
          2 ** Math.min(Math.max(failures - 1, 0), 16),
      );
      const delay = failures > 0 ? retryDelay : regularDelay;
      const withJitter = jitteredDelay(delay, active.options);
      const scheduledDelay =
        failures > 0
          ? Math.min(active.options.maxBackoffMs, withJitter)
          : withJitter;
      active.timer = window.setTimeout(() => {
        active.timer = null;
        void run(active);
      }, scheduledDelay);
    };

    const run = async (active: PollController) => {
      if (controller !== active || active.running) return;
      active.running = true;
      if (active.timer !== null) {
        window.clearTimeout(active.timer);
        active.timer = null;
      }
      try {
        await pollOnce(active.projectId);
      } finally {
        active.running = false;
        if (controller === active) schedule(active);
      }
    };

    return {
      ...reviewBase(),
      reset: (projectId = null) => {
        stopController();
        projectEpoch += 1;
        set(reviewBase(projectId));
      },
      pollOnce,
      decide,
      startPolling: (projectId, overrides = {}) => {
        stopController();
        ensureProject(projectId);
        const active: PollController = {
          token: ++nextControllerToken,
          projectId,
          options: {
            ...DEFAULT_FILE_PROJECT_REVIEW_POLL_OPTIONS,
            ...overrides,
          },
          timer: null,
          running: false,
          visibilityHandler: () => undefined,
        };
        active.visibilityHandler = () => {
          if (controller !== active || active.running) return;
          if (active.timer !== null) {
            window.clearTimeout(active.timer);
            active.timer = null;
          }
          if (isPageVisible()) void run(active);
          else schedule(active);
        };
        controller = active;
        set((state) =>
          state.projectId === projectId ? { polling: true } : {},
        );
        if (typeof document !== "undefined") {
          document.addEventListener(
            "visibilitychange",
            active.visibilityHandler,
          );
        }
        void run(active);
        return () => {
          if (controller?.token === active.token) stopController(projectId);
        };
      },
      stopPolling: stopController,
    };
  },
);
