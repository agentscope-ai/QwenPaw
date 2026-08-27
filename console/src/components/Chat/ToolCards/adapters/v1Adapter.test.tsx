// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import { adaptCardForV1 } from "./v1Adapter";
import { ToolCallTurnEndedContext } from "../shared/ToolCallTurnContext";
import type { ToolCallContent } from "../shared/types";

const Probe = ({
  content,
  isStreaming,
}: {
  content: ToolCallContent;
  isStreaming?: boolean;
}) => (
  <div>
    <span data-testid="status">{content.status}</span>
    <span data-testid="streaming">{String(Boolean(isStreaming))}</span>
    <span data-testid="result">{String(content.result ?? "")}</span>
  </div>
);

const WrappedProbe = adaptCardForV1(Probe);

const callContent = {
  data: {
    call_id: "call-1",
    name: "execute_shell_command",
    arguments: JSON.stringify({ command: "ping 127.0.0.1 -n 31" }),
  },
};

/** A tool call message whose result never arrived. */
const callOnlyProps = {
  data: {
    type: "plugin_call",
    // The call message completes as soon as its arguments are streamed —
    // it says nothing about the execution itself.
    status: "completed",
    content: [callContent],
  },
};

/** A tool call merged with its result message. */
const withOutputProps = (
  output: string,
  state?: string,
  status = "completed",
) => ({
  data: {
    type: "plugin_call_output",
    status,
    content: [
      callContent,
      {
        data: {
          call_id: "call-1",
          name: "execute_shell_command",
          output,
          ...(state ? { state } : {}),
        },
      },
    ],
  },
});

const renderCard = (props: unknown, turnEnded: boolean) =>
  render(
    <ToolCallTurnEndedContext.Provider value={turnEnded}>
      <WrappedProbe {...(props as Record<string, unknown>)} />
    </ToolCallTurnEndedContext.Provider>,
  );

describe("v1Adapter tool status", () => {
  it("keeps a pending call running while its turn streams", () => {
    renderCard(callOnlyProps, false);

    expect(screen.getByTestId("status")).toHaveTextContent("calling");
    expect(screen.getByTestId("streaming")).toHaveTextContent("true");
    expect(screen.getByTestId("result")).toHaveTextContent("");
  });

  it("closes a pending call once its turn ended", () => {
    renderCard(callOnlyProps, true);

    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("streaming")).toHaveTextContent("false");
    expect(screen.getByTestId("result")).toHaveTextContent("tool.interrupted");
  });

  it("reports a completed call as done regardless of turn state", () => {
    renderCard(withOutputProps("pong"), true);

    expect(screen.getByTestId("status")).toHaveTextContent("done");
    expect(screen.getByTestId("streaming")).toHaveTextContent("false");
    expect(screen.getByTestId("result")).toHaveTextContent("pong");
  });

  it("keeps the persisted interruption output of a restored call", () => {
    renderCard(withOutputProps("partial output", "interrupted"), true);

    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("result")).toHaveTextContent("partial output");
  });

  it("closes output that stopped mid-stream when the turn ended", () => {
    const props = withOutputProps("partial output", undefined, "in_progress");

    renderCard(props, false);
    expect(screen.getByTestId("status")).toHaveTextContent("calling");

    renderCard(props, true);
    expect(screen.getAllByTestId("status")[1]).toHaveTextContent("error");
    expect(screen.getAllByTestId("result")[1]).toHaveTextContent(
      "partial output",
    );
  });
});
