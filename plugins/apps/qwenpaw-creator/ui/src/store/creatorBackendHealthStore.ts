import { create } from "zustand";
import { creatorFetch } from "@/api/creator";
import i18n from "@/i18n";
import {
  reportBackendAvailable,
  subscribeBackendHealth,
} from "@/lib/backendHealthSignal";

export type CreatorBackendPhase = "checking" | "ready" | "unavailable";

export interface CreatorBackendHealthState {
  phase: CreatorBackendPhase;
  /** A health probe is in flight; the last known phase stays visible. */
  probing: boolean;
  /** True once a health probe succeeded in this page session. */
  everReady: boolean;
  error: string | null;
  checkedAt: string | null;
  check: () => Promise<boolean>;
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return String(error);
}

export const useCreatorBackendHealthStore = create<CreatorBackendHealthState>(
  (set) => {
    const markUnavailable = (error: string) =>
      set({
        phase: "unavailable" as CreatorBackendPhase,
        error,
        checkedAt: new Date().toISOString(),
      });
    const markReady = () =>
      set({
        phase: "ready",
        everReady: true,
        error: null,
        checkedAt: new Date().toISOString(),
      });

    // Any response that proves the backend is unreachable flips the UI into
    // the not-ready state; any later successful Creator request clears it.
    subscribeBackendHealth((available) => {
      if (available) {
        markReady();
        return;
      }
      set((state) => ({
        phase: "unavailable" as CreatorBackendPhase,
        error: state.error ?? i18n.t("api.backendUnavailable"),
        checkedAt: new Date().toISOString(),
      }));
    });

    return {
      phase: "checking",
      probing: false,
      everReady: false,
      error: null,
      checkedAt: null,
      check: async () => {
        // Keep the last known phase while re-probing: flipping to "checking"
        // would unmount the not-ready page and the blocking overlay, letting
        // the app fire writes at a backend already known to be unavailable.
        set({ probing: true });
        try {
          const response = await creatorFetch(
            "/health",
            {},
            { timeoutMs: 8_000 },
          );
          if (!response.ok) {
            throw new Error(
              response.status === 404 || response.status === 405
                ? i18n.t("api.backendUnavailable")
                : i18n.t("api.requestFailed", { status: response.status }),
            );
          }
          reportBackendAvailable();
          markReady();
          return true;
        } catch (error) {
          markUnavailable(messageOf(error));
          return false;
        } finally {
          set({ probing: false });
        }
      },
    };
  },
);
