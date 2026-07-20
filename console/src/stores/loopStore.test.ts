import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/request", () => ({ request: vi.fn() }));

import { request } from "@/api/request";
import {
  DEFAULT_LOOP_MODE,
  applyLoopModeCommand,
  cancelPendingLoopSubmission,
  fetchActiveLoopMode,
  fetchAvailableLoopModes,
  prepareLoopModeSubmission,
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

  it("starts with Default selected", () => {
    const state = useLoopStore.getState();
    expect(state.selectedModeId).toBe("default");
    expect(state.availableModes).toEqual([DEFAULT_LOOP_MODE]);
    expect(state.sessionState).toBe("idle");
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

  it("keeps Default available when the API returns no modes", async () => {
    mockRequest.mockResolvedValueOnce([]);

    await fetchAvailableLoopModes();

    expect(useLoopStore.getState().availableModes).toEqual([DEFAULT_LOOP_MODE]);
  });

  it("marks catalog errors without removing Default", async () => {
    mockRequest.mockRejectedValueOnce(new Error("offline"));

    await fetchAvailableLoopModes();

    expect(useLoopStore.getState().catalogError).toBe(true);
    expect(useLoopStore.getState().availableModes).toEqual([DEFAULT_LOOP_MODE]);
  });

  it("prefixes an explicitly selected mode and enters starting state", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");

    expect(prepareLoopModeSubmission("fix the tests")).toBe(
      "/goal fix the tests",
    );
    expect(useLoopStore.getState().sessionState).toBe("starting");
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("recognizes a manually typed mode command without duplicating it", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);

    expect(prepareLoopModeSubmission("/goal fix the tests")).toBe(
      "/goal fix the tests",
    );
    expect(useLoopStore.getState().activeMode).toEqual(goal);
  });

  it("does not wrap another slash command in the selected mode", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");

    expect(prepareLoopModeSubmission("/clear")).toBe("/clear");
    expect(useLoopStore.getState().sessionState).toBe("idle");
  });

  it("does not prefix Default or messages in an active session", () => {
    expect(prepareLoopModeSubmission("hello")).toBe("hello");
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setActiveMode(goal);
    useLoopStore.getState().setSelectedMode("goal");
    expect(prepareLoopModeSubmission("continue")).toBe("continue");
  });

  it("restores the selector when a pending activation is cancelled", () => {
    useLoopStore.getState().setAvailableModes([DEFAULT_LOOP_MODE, goal]);
    useLoopStore.getState().setSelectedMode("goal");
    const text = prepareLoopModeSubmission("fix the tests");

    cancelPendingLoopSubmission(text);

    expect(useLoopStore.getState().sessionState).toBe("idle");
    expect(useLoopStore.getState().selectedModeId).toBe("default");
  });

  it("uses an exact command boundary when avoiding duplicate prefixes", () => {
    expect(applyLoopModeCommand("/goalkeeper notes", goal)).toBe(
      "/goal /goalkeeper notes",
    );
    expect(applyLoopModeCommand("/GOAL notes", goal)).toBe("/GOAL notes");
  });

  it("restores the active mode from backend status", async () => {
    mockRequest.mockResolvedValueOnce({ state: "active", mode: custom });

    await fetchActiveLoopMode({
      chatId: "chat-1",
      sessionId: "session-1",
    });

    expect(mockRequest).toHaveBeenCalledWith(
      "/loops/status?chat_id=chat-1&session_id=session-1",
      { signal: undefined },
    );
    expect(useLoopStore.getState().sessionState).toBe("active");
    expect(useLoopStore.getState().activeMode).toEqual(custom);
    expect(useLoopStore.getState().selectedModeId).toBe("default");
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
