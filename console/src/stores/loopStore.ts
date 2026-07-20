import { create } from "zustand";
import { request } from "@/api/request";

export type LoopModeSource = "builtin" | "custom" | "plugin";
export type LoopSessionState = "idle" | "starting" | "active";

export interface LoopModeInfo {
  id: string;
  name: string;
  slash_command: string;
  description: string;
  source: LoopModeSource;
}

interface LoopModeStatusResponse {
  state: "idle" | "active";
  mode: LoopModeInfo | null;
}

export const DEFAULT_LOOP_MODE: LoopModeInfo = {
  id: "default",
  name: "default",
  slash_command: "",
  description: "The standard guarded agent loop.",
  source: "builtin",
};

let catalogRequestId = 0;
let statusRequestId = 0;

interface LoopState {
  selectedModeId: string;
  availableModes: LoopModeInfo[];
  sessionState: LoopSessionState;
  activeMode: LoopModeInfo | null;
  catalogLoading: boolean;
  catalogError: boolean;
  setSelectedMode: (modeId: string) => void;
  setAvailableModes: (modes: LoopModeInfo[]) => void;
  setStartingMode: (mode: LoopModeInfo) => void;
  setActiveMode: (mode: LoopModeInfo | null) => void;
  resetSessionMode: () => void;
  setCatalogLoading: (loading: boolean) => void;
  setCatalogError: (error: boolean) => void;
}

export const useLoopStore = create<LoopState>((set, get) => ({
  selectedModeId: DEFAULT_LOOP_MODE.id,
  availableModes: [DEFAULT_LOOP_MODE],
  sessionState: "idle",
  activeMode: null,
  catalogLoading: false,
  catalogError: false,

  setSelectedMode: (modeId) => set({ selectedModeId: modeId }),
  setAvailableModes: (modes) => {
    const normalized = normalizeModes(modes);
    const selectedModeId = normalized.some(
      (mode) => mode.id === get().selectedModeId,
    )
      ? get().selectedModeId
      : DEFAULT_LOOP_MODE.id;
    set({ availableModes: normalized, selectedModeId });
  },
  setStartingMode: (mode) =>
    set({ sessionState: "starting", activeMode: mode }),
  setActiveMode: (mode) =>
    set({
      sessionState: mode ? "active" : "idle",
      activeMode: mode,
      selectedModeId: DEFAULT_LOOP_MODE.id,
    }),
  resetSessionMode: () =>
    set({
      sessionState: "idle",
      activeMode: null,
      selectedModeId: DEFAULT_LOOP_MODE.id,
    }),
  setCatalogLoading: (loading) => set({ catalogLoading: loading }),
  setCatalogError: (error) => set({ catalogError: error }),
}));

function normalizeModes(modes: LoopModeInfo[]): LoopModeInfo[] {
  const result: LoopModeInfo[] = [];
  const seen = new Set<string>();
  const source = modes.some((mode) => mode.id === DEFAULT_LOOP_MODE.id)
    ? modes
    : [DEFAULT_LOOP_MODE, ...modes];
  source.forEach((mode) => {
    if (!mode.id || seen.has(mode.id)) return;
    seen.add(mode.id);
    result.push(mode);
  });
  return result;
}

export function getSelectedLoopMode(): LoopModeInfo {
  const state = useLoopStore.getState();
  return (
    state.availableModes.find((mode) => mode.id === state.selectedModeId) ??
    DEFAULT_LOOP_MODE
  );
}

export function applyLoopModeCommand(text: string, mode: LoopModeInfo): string {
  const command = mode.slash_command.trim();
  if (!command) return text;
  const trimmed = text.trimStart();
  const prefix = `/${command}`;
  const firstToken = trimmed.split(/\s/, 1)[0];
  if (firstToken.toLowerCase() === prefix.toLowerCase()) return text;
  return `${prefix} ${text}`;
}

export function findLoopModeForCommand(text: string): LoopModeInfo | null {
  const command = text
    .trimStart()
    .match(/^\/(\S+)/)?.[1]
    ?.toLowerCase();
  if (!command) return null;
  return (
    useLoopStore
      .getState()
      .availableModes.find(
        (mode) => mode.slash_command.toLowerCase() === command,
      ) ?? null
  );
}

export function prepareLoopModeSubmission(text: string): string {
  const state = useLoopStore.getState();
  if (state.sessionState !== "idle") return text;
  const selected = getSelectedLoopMode();
  const manual = findLoopModeForCommand(text);
  if (!manual && text.trimStart().startsWith("/")) return text;
  const mode = manual ?? selected;
  if (!mode || mode.id === DEFAULT_LOOP_MODE.id) return text;
  state.setStartingMode(mode);
  return applyLoopModeCommand(text, mode);
}

export function cancelPendingLoopSubmission(text: string): void {
  const state = useLoopStore.getState();
  const mode = findLoopModeForCommand(text);
  if (state.sessionState === "starting" && mode?.id === state.activeMode?.id) {
    state.resetSessionMode();
  }
}

export async function fetchAvailableLoopModes(
  signal?: AbortSignal,
): Promise<void> {
  const requestId = ++catalogRequestId;
  const store = useLoopStore.getState();
  store.setCatalogLoading(true);
  store.setCatalogError(false);
  try {
    const modes = await request<LoopModeInfo[]>("/loops", { signal });
    if (requestId === catalogRequestId) {
      useLoopStore.getState().setAvailableModes(modes ?? []);
    }
  } catch (error) {
    if (
      requestId === catalogRequestId &&
      (error as Error)?.name !== "AbortError"
    ) {
      useLoopStore.getState().setCatalogError(true);
    }
  } finally {
    if (requestId === catalogRequestId) {
      useLoopStore.getState().setCatalogLoading(false);
    }
  }
}

export interface LoopStatusTarget {
  chatId?: string | null;
  sessionId?: string | null;
  signal?: AbortSignal;
}

export async function fetchActiveLoopMode({
  chatId,
  sessionId,
  signal,
}: LoopStatusTarget): Promise<void> {
  const requestId = ++statusRequestId;
  const params = new URLSearchParams();
  if (chatId) params.set("chat_id", chatId);
  if (sessionId) params.set("session_id", sessionId);
  if (params.size === 0) {
    useLoopStore.getState().resetSessionMode();
    return;
  }
  try {
    const status = await request<LoopModeStatusResponse>(
      `/loops/status?${params.toString()}`,
      { signal },
    );
    if (requestId === statusRequestId) {
      useLoopStore
        .getState()
        .setActiveMode(status?.state === "active" ? status.mode : null);
    }
  } catch {
    // Preserve the last known state when synchronization is unavailable.
  }
}
