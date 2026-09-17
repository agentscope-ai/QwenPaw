import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import {
  ONBOARDING_STORAGE_KEY,
  useOnboardingStore,
} from "@/store/onboardingStore";

// jsdom's localStorage is incomplete; replace with an in-memory version.
const memory = new Map<string, string>();

function readStored(): Record<string, unknown> {
  const raw = memory.get(ONBOARDING_STORAGE_KEY);
  expect(raw).toBeTruthy();
  return JSON.parse(raw!) as Record<string, unknown>;
}

beforeAll(() => {
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => memory.get(key) ?? null,
      setItem: (key: string, value: string) => {
        memory.set(key, String(value));
      },
      removeItem: (key: string) => {
        memory.delete(key);
      },
    },
  });
});

beforeEach(() => {
  memory.clear();
  useOnboardingStore.setState({
    homeTourDone: false,
    projectTourDone: false,
    assetsTourDone: false,
    hints: {},
    homeTourRequested: false,
    projectTourRequested: false,
    assetsTourRequested: false,
  });
});

describe("useOnboardingStore", () => {
  it("completes the home tour and clears any pending manual request", () => {
    useOnboardingStore.getState().requestHomeTour();
    expect(useOnboardingStore.getState().homeTourRequested).toBe(true);

    useOnboardingStore.getState().completeHomeTour();
    const state = useOnboardingStore.getState();
    expect(state.homeTourDone).toBe(true);
    expect(state.homeTourRequested).toBe(false);
    expect(readStored().homeTourDone).toBe(true);
    // Runtime request state must not be persisted.
    expect(readStored()).not.toHaveProperty("homeTourRequested");
  });

  it("tracks home, project and assets tours independently", () => {
    useOnboardingStore.getState().completeProjectTour();
    useOnboardingStore.getState().completeAssetsTour();
    const state = useOnboardingStore.getState();
    expect(state.projectTourDone).toBe(true);
    expect(state.assetsTourDone).toBe(true);
    expect(state.homeTourDone).toBe(false);
    expect(readStored().projectTourDone).toBe(true);
    expect(readStored().assetsTourDone).toBe(true);
    expect(readStored().homeTourDone).toBe(false);
  });

  it("marks one-time hints as seen exactly once", () => {
    useOnboardingStore.getState().markHintSeen("mention");
    useOnboardingStore.getState().markHintSeen("mention");
    useOnboardingStore.getState().markHintSeen("review");
    expect(useOnboardingStore.getState().hints).toEqual({
      mention: true,
      review: true,
    });
    expect(readStored().hints).toEqual({ mention: true, review: true });
  });

  it("allows replaying a finished tour via manual request", () => {
    useOnboardingStore.getState().completeProjectTour();
    useOnboardingStore.getState().requestProjectTour();
    const state = useOnboardingStore.getState();
    expect(state.projectTourDone).toBe(true);
    expect(state.projectTourRequested).toBe(true);

    useOnboardingStore.getState().completeProjectTour();
    expect(useOnboardingStore.getState().projectTourRequested).toBe(false);
  });

  it("ignores corrupted persisted payloads gracefully", () => {
    memory.set(ONBOARDING_STORAGE_KEY, "not-json{");
    // markHintSeen re-persists, overwriting corrupted data without throwing.
    expect(() =>
      useOnboardingStore.getState().markHintSeen("addToConversation"),
    ).not.toThrow();
    expect(readStored().hints).toEqual({ addToConversation: true });
  });
});
