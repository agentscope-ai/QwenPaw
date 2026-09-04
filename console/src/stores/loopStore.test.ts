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
  beginLoopModeMessageSubmission,
  prepareLoopModeMessageSubmission,
  useLoopStore,
  DEFAULT_LOOP_MODE,
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
  description: "Run a multi-agent mission",
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
    ["goal", "/goal Fix the failing tests", goalMode],
    ["mission", "/mission Build the feature", missionMode],
  ])(
    "adds the selected %s mode to string message content",
    (_, expected, mode) => {
      useLoopStore.getState().setSelectedMode(mode.id);

      const message = beginLoopModeMessageSubmission({
        role: "user",
        content: expected.replace(/^\/\w+ /, ""),
      });

      expect(message.content).toBe(expected);
      expect(useLoopStore.getState().sessionState).toBe("starting");
      expect(useLoopStore.getState().activeMode).toEqual(mode);
    },
  );

  it("adds the selected mode to the text part of multimodal content", () => {
    useLoopStore.getState().setSelectedMode("goal");

    const message = beginLoopModeMessageSubmission({
      role: "user",
      content: [
        { type: "image_url", image_url: { url: "data:image/png;base64,x" } },
        { type: "text", text: "Describe this image" },
      ],
    });

    expect(message.content).toEqual([
      { type: "image_url", image_url: { url: "data:image/png;base64,x" } },
      { type: "text", text: "/goal Describe this image" },
    ]);
  });

  it("preserves an explicit loop command instead of adding the selected mode", () => {
    useLoopStore.getState().setSelectedMode("goal");

    const message = beginLoopModeMessageSubmission({
      role: "user",
      content: [{ type: "text", text: "/mission Build the feature" }],
    });

    expect(message.content).toEqual([
      { type: "text", text: "/mission Build the feature" },
    ]);
    expect(useLoopStore.getState().activeMode).toEqual(missionMode);
  });

  it("preserves the selected mode while asynchronous request checks run", () => {
    useLoopStore.getState().setSelectedMode("goal");
    const prepared = prepareLoopModeMessageSubmission({
      role: "user",
      content: "Fix the failing tests",
    });

    useLoopStore.getState().resetSessionMode();
    const submitted = beginLoopModeMessageSubmission(prepared);

    expect(submitted.content).toBe("/goal Fix the failing tests");
    expect(useLoopStore.getState().activeMode).toEqual(goalMode);
  });
});
