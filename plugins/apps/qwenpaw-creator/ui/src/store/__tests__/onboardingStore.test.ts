import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import {
  ONBOARDING_STORAGE_KEY,
  useOnboardingStore,
} from "@/store/onboardingStore";

// jsdom's localStorage is incomplete; replace with an in-memory version.
const memory = new Map<string, string>();
const store = () => useOnboardingStore.getState();

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
  it("completes the home tour, clears the request and allows a manual replay", () => {
    store().requestHomeTour();
    expect(store().homeTourRequested).toBe(true);

    store().completeHomeTour();
    expect(store()).toMatchObject({
      homeTourDone: true,
      homeTourRequested: false,
    });
    expect(readStored().homeTourDone).toBe(true);
    // Runtime request state must not be persisted.
    expect(readStored()).not.toHaveProperty("homeTourRequested");

    // A finished tour can still be replayed via manual request.
    store().requestHomeTour();
    expect(store()).toMatchObject({
      homeTourDone: true,
      homeTourRequested: true,
    });
    store().completeHomeTour();
    expect(store().homeTourRequested).toBe(false);
  });

  it("tracks home, project and assets tours independently", () => {
    store().completeProjectTour();
    store().completeAssetsTour();
    const expected = {
      projectTourDone: true,
      assetsTourDone: true,
      homeTourDone: false,
    };
    expect(store()).toMatchObject(expected);
    expect(readStored()).toMatchObject(expected);
  });

  it("marks one-time hints as seen exactly once", () => {
    store().markHintSeen("mention");
    store().markHintSeen("mention");
    store().markHintSeen("review");
    expect(store().hints).toEqual({ mention: true, review: true });
    expect(readStored().hints).toEqual({ mention: true, review: true });
  });

  it("ignores corrupted persisted payloads gracefully", () => {
    memory.set(ONBOARDING_STORAGE_KEY, "not-json{");
    // markHintSeen re-persists, overwriting corrupted data without throwing.
    expect(() => store().markHintSeen("addToConversation")).not.toThrow();
    expect(readStored().hints).toEqual({ addToConversation: true });
  });
});
