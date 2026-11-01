// @vitest-environment jsdom
/**
 * Contract tests for GetCurrentTimeCard.
 *
 * The card has one job beyond decoration: turn the tool result into the short
 * string the shell shows inline. These tests pin that mapping for every result
 * shape the tool can produce (JSON text block, array of blocks, already-parsed
 * object, unparseable text, long text), because that mapping is what the user
 * reads in the collapsed card.
 *
 * There was no test file for this card before this one.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({
    title,
    inlineResult,
  }: {
    title?: string;
    inlineResult?: string | null;
  }) => (
    <div>
      <span data-testid="card-title">{title}</span>
      {inlineResult ? <span data-testid="inline">{inlineResult}</span> : null}
    </div>
  ),
}));

import GetCurrentTimeCard from "./GetCurrentTimeCard";

const createContent = (overrides: Record<string, unknown> = {}) =>
  ({
    type: "tool_call",
    id: "time-1",
    name: "get_current_time",
    status: "done",
    params: {},
    ...overrides,
  }) as never;

const inline = () => screen.queryByTestId("inline");

describe("GetCurrentTimeCard", () => {
  it("titles the card with the translated tool name", () => {
    render(<GetCurrentTimeCard content={createContent({ result: "now" })} />);

    expect(screen.getByTestId("card-title")).toHaveTextContent(
      "tool.getCurrentTime",
    );
  });

  it("shows no inline result while the tool is still running", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({ status: "calling", result: "now" })}
      />,
    );

    expect(inline()).toBeNull();
  });

  it("shows no inline result when the call finished without a result", () => {
    render(
      <GetCurrentTimeCard content={createContent({ result: undefined })} />,
    );

    expect(inline()).toBeNull();
  });

  it("reads the text out of a JSON text-block string", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({
          result: JSON.stringify({ type: "text", text: "2026-09-22 03:00" }),
        })}
      />,
    );

    expect(inline()).toHaveTextContent("2026-09-22 03:00");
  });

  it("joins the text blocks of an array result and skips the other blocks", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({
          result: JSON.stringify([
            { type: "text", text: "first" },
            { type: "image", url: "a.png" },
            { type: "text", text: "second" },
          ]),
        })}
      />,
    );

    expect(inline()).toHaveTextContent("first second");
  });

  it("reads the text out of an already-parsed text block", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({ result: { type: "text", text: "parsed" } })}
      />,
    );

    expect(inline()).toHaveTextContent("parsed");
  });

  it("joins the text blocks of an already-parsed array", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({
          result: [
            { type: "text", text: "alpha" },
            { type: "text", text: "beta" },
          ],
        })}
      />,
    );

    expect(inline()).toHaveTextContent("alpha beta");
  });

  it("shows the result verbatim when it is not valid JSON", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({ result: "not json at all" })}
      />,
    );

    expect(inline()).toHaveTextContent("not json at all");
  });

  it("falls back to the serialized result when the block carries no text", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({ result: { weekday: "Mon" } })}
      />,
    );

    expect(inline()).toHaveTextContent('{"weekday":"Mon"}');
  });

  it("falls back to the serialized result when a text block has empty text", () => {
    render(
      <GetCurrentTimeCard
        content={createContent({ result: { type: "text", text: "" } })}
      />,
    );

    expect(inline()).toHaveTextContent('{"type":"text","text":""}');
  });

  it("keeps a result of exactly 80 characters whole", () => {
    const text = "a".repeat(80);
    render(<GetCurrentTimeCard content={createContent({ result: text })} />);

    expect(inline()).toHaveTextContent(text);
  });

  it("truncates a result longer than 80 characters with an ellipsis", () => {
    const text = "b".repeat(81);
    render(<GetCurrentTimeCard content={createContent({ result: text })} />);

    expect(inline()).toHaveTextContent("b".repeat(80) + "\u2026");
    expect(inline()).not.toHaveTextContent(text);
  });
});
