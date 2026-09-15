// @vitest-environment jsdom
import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BuiltinCardComponent } from "../cards";
import type { ToolCallContent } from "../shared/types";
import { adaptCardForV1 } from "./v1Adapter";

vi.mock("../cards/GenericToolCard", () => ({ default: () => null }));

const Card = adaptCardForV1(() => null);

function adapt(state?: string, status = "completed", hasResult = true) {
  return (
    Card({
      data: {
        status,
        content: [
          { data: { call_id: "call-1", name: "any_tool", arguments: "{}" } },
          ...(hasResult ? [{ data: { state, output: "partial output" } }] : []),
        ],
      },
    }) as ReactElement<{ content: ToolCallContent; isStreaming: boolean }>
  ).props;
}

describe("v1Adapter", () => {
  it("preserves raw input and output for raw tool display", () => {
    let captured: ToolCallContent | undefined;
    const CaptureCard: BuiltinCardComponent = ({ content }) => {
      captured = content;
      return null;
    };
    const WrappedCard = adaptCardForV1(CaptureCard);

    render(
      <WrappedCard
        data={{
          id: "message-1",
          status: "completed",
          content: [
            {
              data: {
                name: "read_file",
                call_id: "call-1",
                arguments: '{"path":"notes.txt"}',
              },
            },
            { data: { output: { text: "contents" } } },
          ],
        }}
      />,
    );

    expect(captured).toMatchObject({
      id: "call-1",
      name: "read_file",
      rawInput: '{"path":"notes.txt"}',
      params: { path: "notes.txt" },
      result: { text: "contents" },
      status: "done",
    });
  });

  it.each([
    ["interrupted", "completed", "interrupted"],
    ["interrupted", "failed", "interrupted"],
    ["interrupted", "in_progress", "interrupted"],
    ["success", "canceled", "done"],
    ["success", "failed", "done"],
    ["success", "in_progress", "done"],
    ["error", "completed", "error"],
    ["denied", "completed", "error"],
    ["running", "completed", "calling"],
    [undefined, "canceled", "interrupted"],
    [undefined, "completed", "done"],
    [undefined, "failed", "error"],
    [undefined, "rejected", "error"],
    [undefined, "in_progress", "calling"],
  ])("maps %s / %s to %s", (state, delivery, expected) => {
    const props = adapt(state, delivery);
    expect(props.content.status).toBe(expected);
    expect(props.isStreaming).toBe(expected === "calling");
    expect(props.content.id).toBe("call-1");
    expect(props.content.result).toBe("partial output");
  });

  it("does not mistake completed call delivery for completed execution", () => {
    expect(adapt(undefined, "completed", false).content.status).toBe("calling");
  });
});
