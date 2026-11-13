import { create } from "zustand";

/**
 * Onboarding state: home tour, project workspace tour, and one-off contextual
 * hints. Pure frontend state persisted in localStorage; never touches project
 * data. The key carries a version number — bump it to re-trigger everything
 * after a major onboarding revamp.
 */
export const ONBOARDING_STORAGE_KEY = "qwenpaw-creator:onboarding:v2";

export type OnboardingHintKey =
  | "executionAuthorization"
  | "review"
  | "mention"
  | "addToConversation";

interface PersistedOnboarding {
  homeTourDone: boolean;
  projectTourDone: boolean;
  assetsTourDone: boolean;
  hints: Partial<Record<OnboardingHintKey, boolean>>;
}

const DEFAULT_PERSISTED: PersistedOnboarding = {
  homeTourDone: false,
  projectTourDone: false,
  assetsTourDone: false,
  hints: {},
};

// Lazy lookup: tests replace window.localStorage; don't capture at load.
function getStorage(): Pick<Storage, "getItem" | "setItem"> | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

function readPersisted(): PersistedOnboarding {
  try {
    const raw = getStorage()?.getItem(ONBOARDING_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PERSISTED };
    const parsed = JSON.parse(raw) as Partial<PersistedOnboarding>;
    return {
      homeTourDone: parsed.homeTourDone === true,
      projectTourDone: parsed.projectTourDone === true,
      assetsTourDone: parsed.assetsTourDone === true,
      hints:
        parsed.hints && typeof parsed.hints === "object" ? parsed.hints : {},
    };
  } catch {
    return { ...DEFAULT_PERSISTED };
  }
}

function persist(state: PersistedOnboarding) {
  try {
    getStorage()?.setItem(
      ONBOARDING_STORAGE_KEY,
      JSON.stringify({
        homeTourDone: state.homeTourDone,
        projectTourDone: state.projectTourDone,
        assetsTourDone: state.assetsTourDone,
        hints: state.hints,
      }),
    );
  } catch {
    // Storage unavailable (private mode): degrade to session-only state.
  }
}

interface OnboardingState extends PersistedOnboarding {
  /** Runtime request from the help entry to re-watch a tour; not persisted. */
  homeTourRequested: boolean;
  projectTourRequested: boolean;
  assetsTourRequested: boolean;
  completeHomeTour: () => void;
  requestHomeTour: () => void;
  completeProjectTour: () => void;
  requestProjectTour: () => void;
  completeAssetsTour: () => void;
  requestAssetsTour: () => void;
  markHintSeen: (key: OnboardingHintKey) => void;
}

export const useOnboardingStore = create<OnboardingState>((set, get) => ({
  ...readPersisted(),
  homeTourRequested: false,
  projectTourRequested: false,
  assetsTourRequested: false,
  completeHomeTour: () => {
    set({ homeTourDone: true, homeTourRequested: false });
    persist(get());
  },
  requestHomeTour: () => set({ homeTourRequested: true }),
  completeProjectTour: () => {
    set({ projectTourDone: true, projectTourRequested: false });
    persist(get());
  },
  requestProjectTour: () => set({ projectTourRequested: true }),
  completeAssetsTour: () => {
    set({ assetsTourDone: true, assetsTourRequested: false });
    persist(get());
  },
  requestAssetsTour: () => set({ assetsTourRequested: true }),
  markHintSeen: (key) => {
    if (get().hints[key]) return;
    set((state) => ({ hints: { ...state.hints, [key]: true } }));
    persist(get());
  },
}));
