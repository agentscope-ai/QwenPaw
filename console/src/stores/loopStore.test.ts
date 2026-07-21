import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/request", () => ({ request: vi.fn() }));

import { request } from "@/api/request";
import {
  DEFAULT_LOOP_MODE,
  applyLoopModeCommand,
  beginLoopModeSubmission,
  fetchActiveLoopMode,
  fetchAvailableLoopModes,
  markLoopModeRunning,
  prepareLoopModeMessage,
  type LoopModeInfo,
  useLoopStore,
} from "./loopStore";

const mockRequest = request as ReturnType<typeof vi.fn>;
const goal: LoopModeInfo = {
  id: "goal",
  name: "goal",
  slash_command: "goal",
  description: "Goal",
  source: "builtin",
};
const custom: LoopModeInfo = {
  id: "custom:quality",
  name: "Quality",
  slash_command: "quality",
  description: "Check quality",
  source: "custom",
};

describe("loopStore", () => {
  beforeEach(() => {
    useLoopStore.setState({
      selectedModeId: DEFAULT_LOOP_MODE.id,
      availableModes: [DEFAULT_LOOP_MODE],
      sessionState: "idle",
      activeMode: null,
      catalogLoading: false,
      catalogError: false,
    });
    vi.clearAllMocks();
  });

  it("loads the complete loop catalog", async () => {
    mockRequest.mockResolvedValueOnce([DEFAULT_LOOP_MODE, goal, custom]);

    await fetchAvailableLoopModes();

    expect(mockRequest).toHaveBeenCalledWith("/loops", {
      signal: undefined,
    });
    expect(useLoopStore.getState().availableModes).toEqual([
      DEFAULT_LOOP_MODE,
      goal,
      custom,
    ]);
  });

  it("marks catalog errors without removing Default", async () => {
    mockRequest.mockRejectedValueOnce(new Error("offline"));

    await fetchAvailableLoopModes();

    expect(useLoopStore.getState().catalogError).toBe(true);
    expect(useLoopStore.getState().availableModes).toEqual([DEFAULT_LOOP_MODE]);
  });

  it("prepares a queued mode without entering starting state", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");

    expect(prepareLoopModeMessage("fix the tests")).toBe("/goal fix the tests");
    expect(useLoopStore.getState().sessionState).toBe("idle");
    expect(useLoopStore.getState().activeMode).toBeNull();
  });

  it("keeps an awaiting mode unchanged while a reply is only queued", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSessionMode(goal, "awaiting_user");

    expect(prepareLoopModeMessage("continue")).toBe("continue");
    expect(useLoopStore.getState().sessionState).toBe("awaiting_user");
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("enters starting only when a selected mode is submitted", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");

    expect(beginLoopModeSubmission("fix the tests")).toBe(
      "/goal fix the tests",
    );
    expect(useLoopStore.getState().sessionState).toBe("starting");
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("recognizes a manually submitted mode command without duplicating it", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);

    expect(beginLoopModeSubmission("/goal fix the tests")).toBe(
      "/goal fix the tests",
    );
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("does not wrap another slash command in the selected mode", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");

    expect(beginLoopModeSubmission("/clear")).toBe("/clear");
    expect(useLoopStore.getState().sessionState).toBe("idle");
  });

  it("does not prefix Default or messages in an active session", () => {
    expect(beginLoopModeSubmission("hello")).toBe("hello");
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSessionMode(goal, "awaiting_user");
    useLoopStore.getState().setSelectedMode("goal");
    expect(beginLoopModeSubmission("continue")).toBe("continue");
    expect(useLoopStore.getState().sessionState).toBe("starting");
  });

  it("moves from starting to running on the first event", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");
    beginLoopModeSubmission("fix the tests");

    markLoopModeRunning();

    expect(useLoopStore.getState().sessionState).toBe("running");
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("uses an exact command boundary when avoiding duplicate prefixes", () => {
    expect(applyLoopModeCommand("/goalkeeper notes", goal)).toBe(
      "/goal /goalkeeper notes",
    );
    expect(applyLoopModeCommand("/GOAL notes", goal)).toBe("/GOAL notes");
  });

  it("restores an awaiting mode from backend status", async () => {
    mockRequest.mockResolvedValueOnce({
      state: "awaiting_user",
      mode: custom,
    });

    await fetchActiveLoopMode({
      chatId: "chat-1",
      sessionId: "session-1",
    });

    expect(mockRequest).toHaveBeenCalledWith(
      "/loops/status?chat_id=chat-1&session_id=session-1",
      { signal: undefined },
    );
    expect(useLoopStore.getState().sessionState).toBe("awaiting_user");
    expect(useLoopStore.getState().activeMode).toEqual(custom);
    expect(useLoopStore.getState().selectedModeId).toBe("default");
  });

  it("restores a running mode from backend status", async () => {
    mockRequest.mockResolvedValueOnce({ state: "running", mode: goal });

    await fetchActiveLoopMode({ sessionId: "session-1" });

    expect(useLoopStore.getState().sessionState).toBe("running");
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("ignores stale status after a new submission starts", async () => {
    let resolveStatus: (value: unknown) => void = () => undefined;
    mockRequest.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveStatus = resolve;
      }),
    );
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");
    const statusPromise = fetchActiveLoopMode({ sessionId: "session-1" });

    beginLoopModeSubmission("fix the tests");
    resolveStatus({ state: "awaiting_user", mode: custom });
    await statusPromise;

    expect(useLoopStore.getState().sessionState).toBe("starting");
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("returns to Default when backend reports idle", async () => {
    useLoopStore.getState().setStartingMode(goal);
    mockRequest.mockResolvedValueOnce({ state: "idle", mode: null });

    await fetchActiveLoopMode({ sessionId: "session-1" });

    expect(useLoopStore.getState().sessionState).toBe("idle");
    expect(useLoopStore.getState().activeMode).toBeNull();
    expect(useLoopStore.getState().selectedModeId).toBe("default");
  });
});
