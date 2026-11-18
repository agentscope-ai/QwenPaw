// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";

vi.mock("../../utils/resolveBackendSessionId", () => ({
  resolveBackendSessionId: (sessionId?: string) =>
    sessionId || "session-active",
}));

import { ToolCallTurnBoundary } from "./turnEndedProvider";
import {
  clearTurnStopped,
  markTurnStopped,
  useStoppedTurnsStore,
} from "./stoppedTurns";
import { useToolCallTurnEnded } from "../../components/Chat/ToolCards/shared/ToolCallTurnContext";

const Probe = () => (
  <span data-testid="turn-ended">{String(useToolCallTurnEnded())}</span>
);

const renderBoundary = (status: string) =>
  render(
    <ToolCallTurnBoundary
      data={{ status, output: [] } as unknown as IAgentScopeRuntimeResponse}
    >
      <Probe />
    </ToolCallTurnBoundary>,
  );

const turnEnded = () => screen.getByTestId("turn-ended");

beforeEach(() => {
  useStoppedTurnsStore.setState({ stoppedSessionIds: new Set() });
});

describe("ToolCallTurnBoundary", () => {
  // A turn keeps streaming tool calls, results and further messages while it
  // is in progress; closing calls here would flag every healthy tool as
  // interrupted until its output arrives.
  it("reports a created turn as running", () => {
    renderBoundary("created");

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("reports an in-progress turn as running", () => {
    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("reports a canceled turn as ended", () => {
    renderBoundary("canceled");

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("reports a failed turn as ended", () => {
    renderBoundary("failed");

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("reports restored history as ended", () => {
    // Session history is rebuilt with a completed status.
    renderBoundary("completed");

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("reports a stopped turn as ended although its status never changed", () => {
    // Stop issued after the stream died: the SDK never observes the abort, so
    // the response stays in progress and only the stop itself is left.
    markTurnStopped("session-active");

    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("ignores a stop recorded for another session", () => {
    useStoppedTurnsStore.setState({
      stoppedSessionIds: new Set(["session-other"]),
    });

    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("reports the next turn as running once the stop signal is cleared", () => {
    markTurnStopped("session-active");
    // Every new stream request clears the signal (customFetch / reconnect).
    clearTurnStopped("session-active");

    renderBoundary("in_progress");

    expect(turnEnded()).toHaveTextContent("false");
  });
});

describe("stoppedTurns", () => {
  it("does not infer a stop target from the active session", () => {
    markTurnStopped();

    expect(useStoppedTurnsStore.getState().stoppedSessionIds).toEqual(
      new Set(),
    );
  });

  it("records the requested session on stop", () => {
    markTurnStopped("session-active");

    expect(useStoppedTurnsStore.getState().stoppedSessionIds).toEqual(
      new Set(["session-active"]),
    );
  });

  it("clears only the requested session", () => {
    markTurnStopped("session-active");
    markTurnStopped("session-other");
    clearTurnStopped("session-active");

    expect(useStoppedTurnsStore.getState().stoppedSessionIds).toEqual(
      new Set(["session-other"]),
    );
  });

  it("keeps the same state object when clearing an unmarked session", () => {
    const before = useStoppedTurnsStore.getState();
    clearTurnStopped("session-active");

    expect(useStoppedTurnsStore.getState()).toBe(before);
  });
});
