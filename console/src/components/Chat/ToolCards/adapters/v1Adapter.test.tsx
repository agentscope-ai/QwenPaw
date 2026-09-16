// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BuiltinCardComponent } from "../cards";
import type { ToolCallContent } from "../shared/types";
import { adaptCardForV1 } from "./v1Adapter";

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
});
