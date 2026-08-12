import { create } from "zustand";

export type LaunchUploadPhase = "uploading" | "messaging" | "done" | "error";

interface LaunchUploadState {
  /** Project currently ingesting its launch attachments, if any. */
  projectId: string | null;
  phase: LaunchUploadPhase;
  total: number;
  done: number;
  failed: number;
  /** File names currently in flight (bounded by the upload pool size). */
  activeNames: string[];
  begin: (projectId: string, total: number) => void;
  fileStarted: (projectId: string, name: string) => void;
  fileFinished: (projectId: string, name: string, ok: boolean) => void;
  messaging: (projectId: string) => void;
  finish: (projectId: string, ok: boolean) => void;
  reset: () => void;
}

/**
 * Launch-time attachment ingest progress, decoupled from the composer's
 * component lifecycle: the composer navigates to the project page right
 * after the Project exists, and the background continuation reports here
 * so the workspace can show "uploading n/m" instead of a silent IDLE.
 *
 * Every mutation is scoped to a projectId: `begin` claims the store for
 * the newest launch, and progress reported by an older, still-running
 * continuation for another project is dropped instead of clobbering the
 * counters of the launch the user is actually watching.
 */
export const useLaunchUploadStore = create<LaunchUploadState>((set) => ({
  projectId: null,
  phase: "done",
  total: 0,
  done: 0,
  failed: 0,
  activeNames: [],
  begin: (projectId, total) =>
    set({
      projectId,
      total,
      done: 0,
      failed: 0,
      phase: "uploading",
      activeNames: [],
    }),
  fileStarted: (projectId, name) =>
    set((state) =>
      state.projectId === projectId
        ? { activeNames: [...state.activeNames, name] }
        : state,
    ),
  fileFinished: (projectId, name, ok) =>
    set((state) =>
      state.projectId === projectId
        ? {
            done: state.done + 1,
            failed: state.failed + (ok ? 0 : 1),
            activeNames: state.activeNames.filter((item) => item !== name),
          }
        : state,
    ),
  messaging: (projectId) =>
    set((state) =>
      state.projectId === projectId
        ? { phase: "messaging", activeNames: [] }
        : state,
    ),
  finish: (projectId, ok) =>
    set((state) =>
      state.projectId === projectId
        ? { phase: ok ? "done" : "error", activeNames: [] }
        : state,
    ),
  reset: () =>
    set({
      projectId: null,
      phase: "done",
      total: 0,
      done: 0,
      failed: 0,
      activeNames: [],
    }),
}));
