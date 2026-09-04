/**
 * loopStore.test.ts — regression for A#85096690 (loop indicator not refreshing)
 *
 * The loop indicator must update when session events arrive:
 *   - idle → starting → running → awaiting_user → idle
 *
 * The bug was that the indicator stayed stale after session events because
 * the store's state transitions didn't properly propagate to the UI.
 *
 * We test the loopStore's state machine directly:
 *   - setStartingMode transitions to "starting"
 *   - setSessionMode transitions to "running" or "awaiting_user"
 *   - resetSessionMode returns to "idle"
 *   - Each transition updates both sessionState and activeMode
 */
import { describe, it, expect, beforeEach } from "vitest";
import {
  useLoopStore,
  DEFAULT_LOOP_MODE,
  beginLoopModeSubmission,
  prepareLoopModeMessage,
  type LoopModeInfo,
} from "./loopStore";

const goalMode: LoopModeInfo = {
  id: "goal",
  name: "Goal Mode",
  slash_command: "goal",
  description: "Run until goal is met",
  source: "builtin",
};

const customMode: LoopModeInfo = {
  id: "custom:review",
  name: "Code Review",
  slash_command: "review",
  description: "Iterative code review loop",
  source: "custom",
};

const missionMode: LoopModeInfo = {
  id: "mission",
  name: "Mission Mode",
  slash_command: "mission",
  description: "Run a structured mission",
  source: "builtin",
};

describe("loopStore state transitions (A#85096690)", () => {
  beforeEach(() => {
    useLoopStore.setState({
      selectedModeId: "default",
      availableModes: [DEFAULT_LOOP_MODE, goalMode, missionMode, customMode],
      sessionState: "idle",
      activeMode: null,
      catalogLoading: false,
      catalogError: false,
    });
  });

  it("starts in idle state with no active mode", () => {
    expect(useLoopStore.getState().sessionState).toBe("idle");
    expect(useLoopStore.getState().activeMode).toBeNull();
  });

  it("transitions to starting when setStartingMode is called", () => {
    useLoopStore.getState().setStartingMode(goalMode);
    const state = useLoopStore.getState();
    expect(state.sessionState).toBe("starting");
    expect(state.activeMode).toEqual(goalMode);
  });

  it("transitions from starting to running on first response event", () => {
    useLoopStore.getState().setStartingMode(goalMode);
    useLoopStore.getState().setRunningMode();
    const state = useLoopStore.getState();
    expect(state.sessionState).toBe("running");
    expect(state.activeMode).toEqual(goalMode);
  });

  it("transitions to running via setSessionMode", () => {
    useLoopStore.getState().setSessionMode(customMode, "running");
    const state = useLoopStore.getState();
    expect(state.sessionState).toBe("running");
    expect(state.activeMode).toEqual(customMode);
  });

  it("transitions to awaiting_user via setSessionMode", () => {
    useLoopStore.getState().setSessionMode(customMode, "awaiting_user");
    const state = useLoopStore.getState();
    expect(state.sessionState).toBe("awaiting_user");
    expect(state.activeMode).toEqual(customMode);
  });

  it("returns to idle after resetSessionMode", () => {
    useLoopStore.getState().setSessionMode(goalMode, "running");
    useLoopStore.getState().resetSessionMode();
    const state = useLoopStore.getState();
    expect(state.sessionState).toBe("idle");
    expect(state.activeMode).toBeNull();
  });

  it("full lifecycle: idle → starting → running → awaiting_user → idle", () => {
    // Start
    useLoopStore.getState().setStartingMode(customMode);
    expect(useLoopStore.getState().sessionState).toBe("starting");

    // First response → running
    useLoopStore.getState().setSessionMode(customMode, "running");
    expect(useLoopStore.getState().sessionState).toBe("running");

    // Needs user input
    useLoopStore.getState().setSessionMode(customMode, "awaiting_user");
    expect(useLoopStore.getState().sessionState).toBe("awaiting_user");

    // User responds, loop completes
    useLoopStore.getState().resetSessionMode();
    expect(useLoopStore.getState().sessionState).toBe("idle");
    expect(useLoopStore.getState().activeMode).toBeNull();
  });

  it("mode selection resets to default after session completes", () => {
    useLoopStore.getState().setSelectedMode("custom:review");
    useLoopStore.getState().setSessionMode(customMode, "running");
    useLoopStore.getState().resetSessionMode();

    // resetSessionMode resets selectedModeId to default — this is by design
    // so the next session starts fresh unless the user explicitly picks a mode
    expect(useLoopStore.getState().selectedModeId).toBe("default");
  });

  it("indicator reflects correct state after rapid transitions", () => {
    // Simulate rapid state changes (e.g., fast loop iterations)
    useLoopStore.getState().setStartingMode(goalMode);
    useLoopStore.getState().setSessionMode(goalMode, "running");
    useLoopStore.getState().resetSessionMode();
    useLoopStore.getState().setStartingMode(customMode);
    useLoopStore.getState().setSessionMode(customMode, "running");

    const state = useLoopStore.getState();
    expect(state.sessionState).toBe("running");
    expect(state.activeMode).toEqual(customMode);
  });

  it.each([
    ["goal", goalMode, "do the task", "/goal do the task"],
    ["mission", missionMode, "build it", "/mission build it"],
    ["custom", customMode, "review it", "/review review it"],
  ])("prepares a selected %s mode command", (_label, mode, text, expected) => {
    useLoopStore.getState().setSelectedMode(mode.id);

    expect(prepareLoopModeMessage(text)).toBe(expected);
  });

  it("leaves default mode messages unchanged", () => {
    expect(prepareLoopModeMessage("hello")).toBe("hello");
  });

  it("does not duplicate a manually entered loop command", () => {
    useLoopStore.getState().setSelectedMode(goalMode.id);

    expect(beginLoopModeSubmission("/goal do the task")).toBe(
      "/goal do the task",
    );
  });

  it("leaves unrelated slash commands unchanged", () => {
    useLoopStore.getState().setSelectedMode(goalMode.id);

    expect(beginLoopModeSubmission("/clear")).toBe("/clear");
  });

  it("leaves follow-up text unchanged while a loop is active", () => {
    useLoopStore.getState().setSessionMode(goalMode, "running");

    expect(beginLoopModeSubmission("continue")).toBe("continue");
  });
});
