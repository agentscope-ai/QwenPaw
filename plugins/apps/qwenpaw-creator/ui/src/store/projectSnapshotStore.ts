import { create } from "zustand";
import {
  CreatorHttpError,
  getProjectSnapshot,
  hashProjectValue,
  newClientId,
  patchProject,
} from "@/api/creator";
import { useCreatorEditBufferStore } from "@/store/creatorEditBufferStore";
import type {
  ProjectDocument,
  ProjectPatchResponse,
  ProjectServerSyncStatus,
} from "@/contracts/creator";
import i18n from "@/i18n";

export type ProjectSnapshotSyncStatus =
  | "idle"
  | "syncing"
  | "not_found"
  | ProjectServerSyncStatus;

export interface ProjectSnapshotPollOptions {
  activeIntervalMs: number;
  hiddenIntervalMs: number;
  retryBaseMs: number;
  maxBackoffMs: number;
  jitterRatio: number;
  random: () => number;
}

export const DEFAULT_PROJECT_SNAPSHOT_POLL_OPTIONS: ProjectSnapshotPollOptions =
  {
    activeIntervalMs: 2_000,
    hiddenIntervalMs: 15_000,
    retryBaseMs: 1_000,
    maxBackoffMs: 30_000,
    jitterRatio: 0.15,
    random: Math.random,
  };

export interface ProjectSnapshotState {
  projectId: string | null;
  project: ProjectDocument | null;
  generation: number | null;
  etag: string | null;
  syncStatus: ProjectSnapshotSyncStatus;
  syncError: string | null;
  lastGoodAt: string | null;
  /** Bundled inspiration example (needs remote original footage on demand). */
  builtinExample: boolean;
  requestInFlight: boolean;
  polling: boolean;
  consecutiveFailures: number;
  issuedRequestSequence: number;
  appliedRequestSequence: number;
  patching: boolean;
  patchError: string | null;
  reset: (projectId?: string | null) => void;
  pollOnce: (projectId: string) => Promise<void>;
  patch: (
    projectId: string,
    operations: ProjectEditOperation[],
  ) => Promise<ProjectPatchResponse>;
  startPolling: (
    projectId: string,
    options?: Partial<ProjectSnapshotPollOptions>,
  ) => () => void;
  stopPolling: (projectId?: string) => void;
}

export interface ProjectEditOperation {
  op: "add" | "replace" | "remove";
  path: string;
  before?: unknown;
  value?: unknown;
  /** add operations target a field that is absent from the base document. */
  missingBefore?: boolean;
}

interface RequestToken {
  epoch: number;
  projectId: string;
  sequence: number;
}

interface PollController {
  token: number;
  projectId: string;
  options: ProjectSnapshotPollOptions;
  timer: number | null;
  runPending: boolean;
  visibilityHandler: () => void;
}

const snapshotBase = (projectId: string | null = null) => ({
  projectId,
  project: null,
  generation: null,
  etag: null,
  syncStatus: "idle" as ProjectSnapshotSyncStatus,
  syncError: null,
  lastGoodAt: null,
  builtinExample: false,
  requestInFlight: false,
  polling: false,
  consecutiveFailures: 0,
  issuedRequestSequence: 0,
  appliedRequestSequence: 0,
  patching: false,
  patchError: null,
});

function isPageVisible(): boolean {
  return (
    typeof document === "undefined" || document.visibilityState !== "hidden"
  );
}

function semanticEtag(etag: string): string {
  return etag.trim().replace(/^W\//, "").replace(/^"|"$/g, "");
}

function sameEtag(left: string, right: string): boolean {
  return semanticEtag(left) === semanticEtag(right);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function jitteredDelay(
  delay: number,
  options: ProjectSnapshotPollOptions,
): number {
  const ratio = Math.max(0, Math.min(1, options.jitterRatio));
  const sample = Math.max(0, Math.min(1, options.random()));
  const offset = (sample * 2 - 1) * ratio;
  return Math.max(0, Math.round(delay * (1 + offset)));
}

export const useProjectSnapshotStore = create<ProjectSnapshotState>(
  (set, get) => {
    let projectEpoch = 0;
    let nextRequestSequence = 0;
    let nextControllerToken = 0;
    let controller: PollController | null = null;
    const inFlightByProject = new Map<string, Promise<void>>();

    const ensureProject = (projectId: string) => {
      if (get().projectId === projectId) return;
      projectEpoch += 1;
      set(snapshotBase(projectId));
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
      const sequence = ++nextRequestSequence;
      const token: RequestToken = { epoch: projectEpoch, projectId, sequence };
      const requestEtag = get().projectId === projectId ? get().etag : null;
      set((state) =>
        state.projectId === projectId
          ? {
              requestInFlight: true,
              issuedRequestSequence: sequence,
              syncStatus: state.project ? state.syncStatus : "syncing",
            }
          : {},
      );

      const request = (async () => {
        try {
          const result = await getProjectSnapshot(projectId, requestEtag);
          set((state) => {
            if (
              token.epoch !== projectEpoch ||
              state.projectId !== token.projectId ||
              token.sequence < state.appliedRequestSequence
            )
              return {};

            const finished =
              state.issuedRequestSequence === token.sequence
                ? { requestInFlight: false }
                : {};
            const applied = {
              appliedRequestSequence: token.sequence,
              ...finished,
            };

            if (result.kind === "invalid") {
              return {
                ...applied,
                syncStatus: "invalid" as const,
                syncError: result.message,
                consecutiveFailures: state.consecutiveFailures + 1,
              };
            }

            if (result.kind === "not_modified") {
              if (!state.project || state.generation === null || !state.etag) {
                return {
                  ...applied,
                  syncStatus: "degraded" as const,
                  syncError:
                    "Project snapshot returned 304 before a last-good snapshot was loaded",
                  consecutiveFailures: state.consecutiveFailures + 1,
                };
              }
              if (
                (result.generation !== null &&
                  result.generation !== state.generation) ||
                (result.etag !== null && !sameEtag(result.etag, state.etag))
              ) {
                return {
                  ...applied,
                  syncStatus: "degraded" as const,
                  syncError:
                    "Project snapshot 304 metadata does not match the last-good snapshot",
                  consecutiveFailures: state.consecutiveFailures + 1,
                };
              }
              return {
                ...applied,
                etag: result.etag ?? state.etag,
                syncStatus: result.syncStatus,
                syncError:
                  result.syncStatus === "healthy" ? null : state.syncError,
                consecutiveFailures:
                  result.syncStatus === "healthy"
                    ? 0
                    : state.consecutiveFailures + 1,
              };
            }

            if (
              state.generation !== null &&
              result.generation < state.generation
            ) {
              // A late response can complete after a newer local confirmation.
              // Mark its sequence consumed but never roll Project authority back.
              return applied;
            }
            if (
              state.generation === result.generation &&
              state.etag &&
              !sameEtag(state.etag, result.etag)
            ) {
              return {
                ...applied,
                syncStatus: "invalid" as const,
                syncError: "Project ETag changed without a generation increase",
                consecutiveFailures: state.consecutiveFailures + 1,
              };
            }
            return {
              ...applied,
              project: result.project,
              generation: result.generation,
              etag: result.etag,
              syncStatus: result.syncStatus,
              builtinExample: result.builtinExample === true,
              syncError:
                result.syncStatus === "healthy" ? null : state.syncError,
              lastGoodAt: new Date().toISOString(),
              consecutiveFailures:
                result.syncStatus === "healthy"
                  ? 0
                  : state.consecutiveFailures + 1,
            };
          });
        } catch (error) {
          const projectDeleted =
            error instanceof CreatorHttpError && error.status === 404;
          set((state) => {
            if (
              token.epoch !== projectEpoch ||
              state.projectId !== token.projectId ||
              token.sequence < state.appliedRequestSequence
            )
              return {};
            if (projectDeleted) {
              return {
                ...snapshotBase(projectId),
                polling: state.polling,
                issuedRequestSequence: state.issuedRequestSequence,
                appliedRequestSequence: token.sequence,
                syncStatus: "not_found" as const,
                syncError: errorMessage(error),
              };
            }
            return {
              ...(state.issuedRequestSequence === token.sequence
                ? { requestInFlight: false }
                : {}),
              appliedRequestSequence: token.sequence,
              syncStatus: "degraded",
              syncError: errorMessage(error),
              consecutiveFailures: state.consecutiveFailures + 1,
            };
          });
          if (
            projectDeleted &&
            token.epoch === projectEpoch &&
            get().projectId === token.projectId
          ) {
            // A 404 is a lifecycle result, not a transient sync failure. Stop
            // retaining/polling the deleted authority until the route remounts
            // or a caller explicitly starts a new Project scope.
            stopController(projectId);
          }
        }
      })();
      inFlightByProject.set(projectId, request);
      void request.finally(() => {
        if (inFlightByProject.get(projectId) === request) {
          inFlightByProject.delete(projectId);
        }
      });
      return request;
    };

    const patch = async (projectId: string, edits: ProjectEditOperation[]) => {
      ensureProject(projectId);
      const state = get();
      if (!state.project || state.generation === null || !state.etag) {
        throw new Error(i18n.t("store.snapshotNotLoad"));
      }
      if (!edits.length) {
        throw new Error(i18n.t("store.noOpsToApply"));
      }
      set({ patching: true, patchError: null });
      try {
        const operations = await Promise.all(
          edits.map(async (edit) => ({
            op: edit.op,
            path: edit.path,
            ...(edit.op === "remove" ? {} : { value: edit.value }),
            expectedValueHash: await hashProjectValue(
              edit.before,
              edit.missingBefore === true,
            ),
          })),
        );
        const clientCommandId = newClientId("project-patch");
        const response = await patchProject(projectId, {
          clientCommandId,
          editSessionId: `frontend:${projectId}`,
          baseGeneration: state.generation,
          baseEtag: state.etag,
          operations,
        });
        // Every successful frontend patch is a manual user edit; buffer it so
        // the next AgentDock message can carry the change history as context.
        useCreatorEditBufferStore.getState().recordPatch({
          projectId,
          projectBefore: state.project,
          operations: edits,
          generation: response.generation,
        });
        set((current) => {
          if (current.projectId !== projectId) return {};
          if (
            current.generation !== null &&
            current.generation > response.generation
          ) {
            return { patching: false };
          }
          return {
            project: response.project,
            generation: response.generation,
            etag: response.etag,
            syncStatus: "healthy",
            syncError: null,
            lastGoodAt: new Date().toISOString(),
            patching: false,
            patchError: null,
          };
        });
        return response;
      } catch (error) {
        const message = errorMessage(error);
        set((current) =>
          current.projectId === projectId
            ? { patching: false, patchError: message }
            : {},
        );
        throw error;
      }
    };

    const schedule = (active: PollController) => {
      if (controller !== active || active.runPending) return;
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
      if (controller !== active || active.runPending) return;
      active.runPending = true;
      if (active.timer !== null) {
        window.clearTimeout(active.timer);
        active.timer = null;
      }
      try {
        await pollOnce(active.projectId);
      } finally {
        active.runPending = false;
        if (controller === active) schedule(active);
      }
    };

    return {
      ...snapshotBase(),
      reset: (projectId = null) => {
        stopController();
        projectEpoch += 1;
        set(snapshotBase(projectId));
      },
      pollOnce,
      patch,
      startPolling: (projectId, overrides = {}) => {
        stopController();
        ensureProject(projectId);
        const options: ProjectSnapshotPollOptions = {
          ...DEFAULT_PROJECT_SNAPSHOT_POLL_OPTIONS,
          ...overrides,
        };
        const active: PollController = {
          token: ++nextControllerToken,
          projectId,
          options,
          timer: null,
          runPending: false,
          visibilityHandler: () => undefined,
        };
        active.visibilityHandler = () => {
          if (controller !== active || active.runPending) return;
          if (active.timer !== null) {
            window.clearTimeout(active.timer);
            active.timer = null;
          }
          // Becoming visible should reconcile immediately; hidden tabs simply
          // move onto their lower-frequency interval.
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
