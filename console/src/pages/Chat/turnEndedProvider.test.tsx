// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { IAgentScopeRuntimeResponse } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/types";
import {
  ChatStreamingProvider,
  ToolCallTurnBoundary,
} from "./turnEndedProvider";
import { useToolCallTurnEnded } from "../../components/Chat/ToolCards/shared/ToolCallTurnContext";

const Probe = () => (
  <span data-testid="turn-ended">{String(useToolCallTurnEnded())}</span>
);

const response = (status: string) =>
  ({ status, output: [] }) as unknown as IAgentScopeRuntimeResponse;

const renderBoundary = (opts: {
  status: string;
  isLast?: boolean;
  streaming: boolean;
}) =>
  render(
    <ChatStreamingProvider streaming={opts.streaming}>
      <ToolCallTurnBoundary data={response(opts.status)} isLast={opts.isLast}>
        <Probe />
      </ToolCallTurnBoundary>
    </ChatStreamingProvider>,
  );

const turnEnded = () => screen.getByTestId("turn-ended");

describe("ToolCallTurnBoundary", () => {
  it("reports the streaming turn as still running", () => {
    renderBoundary({ status: "in_progress", isLast: true, streaming: true });

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("reports a stale in-progress turn as ended once streaming stopped", () => {
    // Stop after the stream already died: the SDK never gets to flip the
    // response to canceled, so streaming state is the only signal left.
    renderBoundary({ status: "in_progress", isLast: true, streaming: false });

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("reports a turn that is no longer the newest bubble as ended", () => {
    renderBoundary({ status: "in_progress", isLast: false, streaming: true });

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("trusts a terminal response status while another turn streams", () => {
    renderBoundary({ status: "canceled", isLast: true, streaming: true });

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("reports restored history as ended", () => {
    renderBoundary({ status: "completed", isLast: false, streaming: false });

    expect(turnEnded()).toHaveTextContent("true");
  });

  it("treats an unknown bubble position as possibly streaming", () => {
    renderBoundary({ status: "in_progress", streaming: true });

    expect(turnEnded()).toHaveTextContent("false");
  });

  it("keeps a call running when no streaming provider is mounted", () => {
    // Cards rendered outside the chat page have no turn information; keeping
    // them running is the safe default.
    render(
      <ToolCallTurnBoundary data={response("in_progress")} isLast>
        <Probe />
      </ToolCallTurnBoundary>,
    );

    expect(turnEnded()).toHaveTextContent("false");
  });
});
